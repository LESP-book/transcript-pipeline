from __future__ import annotations

import json
import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from src.runtime_utils import ensure_directory
from src.schemas import LoadedSettings

MIN_EXTRACTED_PDF_TEXT_LENGTH = 10
META_LINE_MARKERS = (
    "CRITICAL INSTRUCTION",
    "EPHEMERAL_MESSAGE",
    "Now I have the text content",
    "Let's read the text content",
    "OK, I will output",
    "I will read through carefully",
    "I just need to return it",
    "Page 1 ends with",
    "The following is an ephemeral message",
    "你现在要对一份中文 PDF 做 OCR 提取",
    "任务要求",
    "只输出提取后的纯文本",
    "不要解释",
    "请处理这个 PDF 文件",
    "我将读取 PDF 文件",
)
OCR_SECTION_LABEL_SUFFIXES = ("段", "章", "节", "篇", "部分", "附录")


class ReferencePreparationError(RuntimeError):
    """Raised when reference preparation fails."""


class ReferenceInputEmptyError(ReferencePreparationError):
    """Raised when there are no supported reference files to process."""


class PdfDependencyError(ReferencePreparationError):
    """Raised when PDF extraction dependencies are missing."""


class GeminiOCRError(ReferencePreparationError):
    """Raised when Gemini CLI OCR fails."""


class CodexOCRError(ReferencePreparationError):
    """Raised when Codex CLI OCR fails."""


@dataclass(frozen=True)
class ReferenceOutputPaths:
    txt_path: Path
    json_path: Path


@dataclass(frozen=True)
class ReferenceFileResult:
    source_file: str
    source_type: str
    output_text_file: str
    extraction_method: str
    success: bool
    text_length: int
    warnings: list[str]
    extracted_text: str


@dataclass(frozen=True)
class ReferenceBatchItem:
    source_path: Path
    output_paths: ReferenceOutputPaths
    success: bool
    warnings: list[str]


@dataclass(frozen=True)
class ReferenceBatchSummary:
    total: int
    success: int
    skipped: int
    failed: int
    items: list[ReferenceBatchItem]


def normalize_extension(extension: str) -> str:
    normalized = extension.strip().lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized


def get_supported_reference_extensions(loaded_settings: LoadedSettings) -> list[str]:
    settings = loaded_settings.settings.reference
    extensions: list[str] = []
    if settings.allow_txt:
        extensions.append(".txt")
    if settings.allow_md:
        extensions.append(".md")
    if settings.allow_pdf:
        extensions.append(".pdf")
    return extensions


def iter_reference_files(reference_dir: Path, allowed_extensions: Iterable[str]) -> list[Path]:
    normalized_extensions = {normalize_extension(extension) for extension in allowed_extensions}
    if not reference_dir.exists():
        return []

    return sorted(
        path
        for path in reference_dir.iterdir()
        if path.is_file() and path.suffix.lower() in normalized_extensions
    )


def build_reference_output_paths(reference_path: Path, output_dir: Path) -> ReferenceOutputPaths:
    return ReferenceOutputPaths(
        txt_path=output_dir / f"{reference_path.stem}.txt",
        json_path=output_dir / f"{reference_path.stem}.json",
    )


def build_source_file_label(source_path: Path, loaded_settings: LoadedSettings) -> str:
    try:
        return str(source_path.resolve().relative_to(loaded_settings.project_root))
    except ValueError:
        return str(source_path.resolve())


def read_text_file(reference_path: Path) -> str:
    try:
        return reference_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return reference_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ReferencePreparationError(f"读取文件失败: {reference_path.name} | {exc}") from exc


def is_effectively_empty_text(text: str) -> bool:
    return len("".join(text.split())) < MIN_EXTRACTED_PDF_TEXT_LENGTH


def import_pdf_reader() -> Callable[[str], object]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfDependencyError("未安装 pypdf。请先执行 `pip install -r requirements.txt`。") from exc

    return PdfReader


def extract_pdf_text(reference_path: Path) -> tuple[str, list[str]]:
    PdfReader = import_pdf_reader()
    warnings: list[str] = []

    try:
        reader = PdfReader(str(reference_path))
    except Exception as exc:
        raise ReferencePreparationError(f"PDF 打开失败: {reference_path.name} | {exc}") from exc

    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            raise ReferencePreparationError(f"PDF 文本提取失败: {reference_path.name} | {exc}") from exc
        if page_text:
            parts.append(page_text)

    text = "\n".join(parts).strip()
    if is_effectively_empty_text(text):
        warnings.append("PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。")

    return text, warnings


def get_ocr_language_code(loaded_settings: LoadedSettings) -> str:
    languages = [language.strip() for language in loaded_settings.settings.reference.ocr_languages if language.strip()]
    if not languages:
        return "chi_sim+eng"
    return "+".join(languages)


def is_gemini_capacity_error(text: str) -> bool:
    normalized = text.upper()
    return "429" in normalized or "MODEL_CAPACITY_EXHAUSTED" in normalized or "RESOURCE_EXHAUSTED" in normalized


def strip_fenced_text(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", candidate)
        candidate = re.sub(r"\n?```$", "", candidate)
    return candidate.strip()


def is_cjk_content_line(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def is_page_marker_line(text: str) -> bool:
    stripped = text.strip()
    return bool(re.fullmatch(r"\[Page\s+\d+\]", stripped, flags=re.IGNORECASE)) or bool(
        re.fullmatch(r"Page\s+\d+:?", stripped, flags=re.IGNORECASE)
    )


def is_page_number_line(text: str) -> bool:
    return bool(re.fullmatch(r"\d{1,4}", text.strip()))


def is_meta_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    normalized = stripped.lower()
    return any(marker.lower() in normalized for marker in META_LINE_MARKERS)


def strip_leading_ascii_noise(text: str) -> str:
    return re.sub(r"^[A-Za-z0-9`~!@#$%^&*()_+\-=\[\]{}|\\:;\"'<>,.?/\s]+(?=[\u3400-\u9fff])", "", text).strip()


def normalize_ocrmypdf_edge_line(text: str) -> str:
    normalized = re.sub(r"\d+", "#", text.strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def normalize_ocrmypdf_body_line(text: str) -> str:
    normalized = re.sub(r"[ \t]{2,}", " ", text)
    normalized = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[，。；：！？、“”‘’《》（）])", "", normalized)
    normalized = re.sub(r"(?<=[，。；：！？、“”‘’《》（）])\s+(?=[\u3400-\u9fff])", "", normalized)
    tokens = normalized.strip().split(" ")
    if len(tokens) <= 1:
        return normalized.strip()

    merged_tokens: list[str] = [tokens[0]]
    for token in tokens[1:]:
        previous = merged_tokens[-1]
        previous_tail = re.search(r"[\u3400-\u9fff]+$", previous)
        current_head = re.match(r"^[\u3400-\u9fff]+", token)
        should_merge = (
            previous_tail is not None
            and current_head is not None
            and (len(previous_tail.group(0)) == 1 or len(current_head.group(0)) == 1)
            and not previous.endswith(OCR_SECTION_LABEL_SUFFIXES)
        )
        if should_merge:
            merged_tokens[-1] = previous + token
        else:
            merged_tokens.append(token)

    return " ".join(merged_tokens).strip()


def is_likely_ocrmypdf_header_footer(text: str) -> bool:
    stripped = text.strip()
    return (
        len(stripped) <= 40
        and bool(re.search(r"\d", stripped))
        and is_cjk_content_line(stripped)
        and not bool(re.search(r"[。！？；]", stripped))
    )


def is_likely_ocrmypdf_garbled_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    cjk_count = len(re.findall(r"[\u3400-\u9fff]", stripped))
    ascii_alpha_count = len(re.findall(r"[A-Za-z]", stripped))
    digit_count = len(re.findall(r"\d", stripped))
    visible_len = len(re.sub(r"\s+", "", stripped))

    return (
        cjk_count <= 2
        and ascii_alpha_count >= 6
        and ascii_alpha_count + digit_count >= max(8, visible_len // 2)
    )


def is_likely_ocrmypdf_tiny_garbage_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped or is_page_number_line(stripped):
        return False

    visible = re.sub(r"\s+", "", stripped)
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", visible))
    ascii_alpha_count = len(re.findall(r"[A-Za-z]", visible))
    digit_count = len(re.findall(r"\d", visible))
    punctuation_count = len(re.findall(r"[^A-Za-z0-9\u3400-\u9fff]", visible))

    return (
        len(visible) <= 4
        and cjk_count == 0
        and ascii_alpha_count + digit_count + punctuation_count == len(visible)
        and (punctuation_count >= 1 or ascii_alpha_count >= 2)
    )


def should_merge_ocrmypdf_lines(previous: str, current: str) -> bool:
    if not previous or not current:
        return False

    if previous.endswith(("。", "！", "？", "；", "：")):
        return False

    if re.match(r"^第[一二三四五六七八九十百千万0-9]+[章节篇部卷节回讲]", current):
        return False

    previous_has_cjk_tail = bool(re.search(r"[\u3400-\u9fff]$", previous))
    current_has_cjk_head = bool(re.match(r"^[\u3400-\u9fff，。；：！？、“”‘’《》（）]", current))
    return previous_has_cjk_tail and current_has_cjk_head


def merge_ocrmypdf_body_lines(lines: list[str]) -> list[str]:
    merged_lines: list[str] = []
    for line in lines:
        if merged_lines and should_merge_ocrmypdf_lines(merged_lines[-1], line):
            merged_lines[-1] = f"{merged_lines[-1]}{line}"
            continue
        merged_lines.append(line)
    return merged_lines


def sanitize_ocrmypdf_text(text: str) -> str:
    raw_pages = [page for page in text.replace("\r\n", "\n").split("\f")]
    page_lines: list[list[str]] = []

    for raw_page in raw_pages:
        lines = [normalize_ocrmypdf_body_line(line) for line in raw_page.splitlines()]
        lines = [line for line in lines if line]
        if lines:
            page_lines.append(lines)

    edge_counts: dict[str, int] = {}
    for lines in page_lines:
        for candidate in (lines[:1] + lines[-1:]):
            key = normalize_ocrmypdf_edge_line(candidate)
            if key:
                edge_counts[key] = edge_counts.get(key, 0) + 1

    cleaned_pages: list[str] = []
    for lines in page_lines:
        start = 0
        end = len(lines)

        while start < end:
            line = lines[start]
            key = normalize_ocrmypdf_edge_line(line)
            if (
                is_page_number_line(line)
                or edge_counts.get(key, 0) >= 2
                or is_likely_ocrmypdf_header_footer(line)
            ):
                start += 1
                continue
            break

        while end > start:
            line = lines[end - 1]
            key = normalize_ocrmypdf_edge_line(line)
            if (
                is_page_number_line(line)
                or edge_counts.get(key, 0) >= 2
                or is_likely_ocrmypdf_header_footer(line)
            ):
                end -= 1
                continue
            break

        page_body_lines = [
            line
            for line in lines[start:end]
            if not is_page_number_line(line)
            and not is_likely_ocrmypdf_garbled_line(line)
            and not is_likely_ocrmypdf_tiny_garbage_line(line)
        ]
        page_body_lines = merge_ocrmypdf_body_lines(page_body_lines)
        cleaned_page = "\n".join(page_body_lines).strip()
        if cleaned_page:
            cleaned_pages.append(cleaned_page)

    return "\n\n".join(cleaned_pages).strip()


def sanitize_gemini_ocr_text(text: str) -> str:
    candidate = strip_fenced_text(text)
    output_lines: list[str] = []
    started = False

    for raw_line in candidate.splitlines():
        line = raw_line.strip()
        if not line:
            if started and output_lines and output_lines[-1] != "":
                output_lines.append("")
            continue

        if is_meta_line(line):
            if started:
                break
            continue

        if is_page_marker_line(line):
            started = True
            continue

        if is_page_number_line(line):
            if started:
                continue
            continue

        if not started and not is_cjk_content_line(line):
            continue

        started = True
        output_lines.append(strip_leading_ascii_noise(line))

    while output_lines and output_lines[-1] == "":
        output_lines.pop()

    return "\n".join(output_lines).strip()


def build_gemini_ocr_prompt(reference_path: str | Path) -> str:
    return "\n".join(
        [
            "你现在要对一份中文 PDF 做 OCR 提取。",
            "任务要求：",
            "1. 只输出提取后的纯文本。",
            "2. 不要解释，不要总结，不要添加说明。",
            "3. 保留原文顺序，尽量保留自然段。",
            "4. 不要输出 Markdown，不要输出 JSON。",
            "5. 不要输出页码、分页标记、页眉、页尾、Page 1 之类的分页提示。",
            "",
            f"请处理这个 PDF 文件：@{{{reference_path}}}",
        ]
    )


def build_codex_ocr_prompt(reference_path: str | Path) -> str:
    return "\n".join(
        [
            "你现在要对一份中文 PDF 做 OCR 提取。",
            "任务要求：",
            "1. 只输出提取后的纯文本。",
            "2. 不要解释，不要总结，不要添加说明。",
            "3. 保留原文顺序，尽量保留自然段。",
            "4. 不要输出 Markdown，不要输出 JSON。",
            "5. 不要输出页码、分页标记、页眉、页尾、Page 1 之类的分页提示。",
            "6. 强制要求：禁止调用本机的 OCR 工具、外部命令、脚本或系统程序。",
            "7. 强制要求：只使用模型自身的视觉能力直接阅读这个 PDF。",
            "",
            f"请处理这个 PDF 文件：@{{{reference_path}}}",
        ]
    )


def build_gemini_ocr_workspace(reference_path: Path, loaded_settings: LoadedSettings) -> tuple[Path, Path]:
    ocr_dir = ensure_directory(loaded_settings.path_for("ocr_dir"))
    source_fingerprint = hashlib.sha1(str(reference_path.resolve()).encode("utf-8")).hexdigest()[:10]
    workspace_dir = ensure_directory(ocr_dir / "gemini_cli_workspace" / f"{reference_path.stem}-{source_fingerprint}")
    staged_pdf_path = workspace_dir / reference_path.name
    if staged_pdf_path.resolve() != reference_path.resolve():
        shutil.copy2(reference_path, staged_pdf_path)
    return workspace_dir, staged_pdf_path


def build_codex_ocr_workspace(reference_path: Path, loaded_settings: LoadedSettings) -> tuple[Path, Path]:
    ocr_dir = ensure_directory(loaded_settings.path_for("ocr_dir"))
    source_fingerprint = hashlib.sha1(str(reference_path.resolve()).encode("utf-8")).hexdigest()[:10]
    workspace_dir = ensure_directory(ocr_dir / "codex_cli_workspace" / f"{reference_path.stem}-{source_fingerprint}")
    staged_pdf_path = workspace_dir / reference_path.name
    if staged_pdf_path.resolve() != reference_path.resolve():
        shutil.copy2(reference_path, staged_pdf_path)
    return workspace_dir, staged_pdf_path


def run_gemini_pdf_ocr(reference_path: Path, loaded_settings: LoadedSettings) -> tuple[str, list[str]]:
    if shutil.which("gemini") is None:
        raise GeminiOCRError("未找到 gemini CLI，无法执行 Gemini OCR。")

    reference_settings = loaded_settings.settings.reference
    models_to_try = [reference_settings.gemini_ocr_model]
    fallback_model = reference_settings.gemini_ocr_fallback_model.strip()
    if fallback_model and fallback_model not in models_to_try:
        models_to_try.append(fallback_model)

    workspace_dir, staged_pdf_path = build_gemini_ocr_workspace(reference_path, loaded_settings)
    prompt = build_gemini_ocr_prompt(staged_pdf_path.name)
    last_error: str | None = None

    for index, model_name in enumerate(models_to_try):
        command = ["gemini", "-m", model_name, "-p", prompt]
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                cwd=str(workspace_dir),
                timeout=loaded_settings.settings.reference.ocr_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GeminiOCRError(f"Gemini OCR 超时: {reference_path.name}") from exc
        except OSError as exc:
            raise GeminiOCRError(f"Gemini OCR 启动失败: {reference_path.name} | {exc}") from exc

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            last_error = stderr or f"gemini exited with code {completed.returncode}"
            if is_gemini_capacity_error(last_error) and index < len(models_to_try) - 1:
                continue
            raise GeminiOCRError(f"Gemini OCR 失败: {reference_path.name} | {last_error}")

        text = sanitize_gemini_ocr_text(completed.stdout)
        if is_effectively_empty_text(text):
            last_error = "Gemini OCR 返回为空或接近空"
            continue

        ocr_dir = ensure_directory(loaded_settings.path_for("ocr_dir"))
        sidecar_path = ocr_dir / f"{reference_path.stem}.gemini_ocr.txt"
        sidecar_path.write_text(text, encoding="utf-8")
        return text, [f"PDF 文字层为空，已使用 Gemini OCR fallback。model={model_name}"]

    raise GeminiOCRError(f"Gemini OCR 未返回有效文本: {reference_path.name} | {last_error or 'unknown error'}")


def run_codex_pdf_ocr(reference_path: Path, loaded_settings: LoadedSettings) -> tuple[str, list[str]]:
    if shutil.which("codex") is None:
        raise CodexOCRError("未找到 codex CLI，无法执行 Codex OCR。")

    reference_settings = loaded_settings.settings.reference
    workspace_dir, staged_pdf_path = build_codex_ocr_workspace(reference_path, loaded_settings)
    prompt = build_codex_ocr_prompt(staged_pdf_path.name)

    command = [
        "codex",
        "exec",
        "-C",
        str(workspace_dir.resolve()),
        "-s",
        "read-only",
    ]
    configured_model = reference_settings.codex_ocr_model.strip()
    configured_reasoning_effort = reference_settings.codex_ocr_reasoning_effort.strip()
    if configured_model:
        command.extend(["-m", configured_model])
    if configured_reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{configured_reasoning_effort}"'])

    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".txt", delete=True, dir=workspace_dir) as output_file:
        command.extend(["-o", output_file.name, "-"])
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                cwd=str(workspace_dir),
                timeout=reference_settings.ocr_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexOCRError(f"Codex OCR 超时: {reference_path.name}") from exc
        except OSError as exc:
            raise CodexOCRError(f"Codex OCR 启动失败: {reference_path.name} | {exc}") from exc

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise CodexOCRError(f"Codex OCR 失败: {reference_path.name} | {stderr or f'codex exited with code {completed.returncode}'}")

        output_file.seek(0)
        text = sanitize_gemini_ocr_text(output_file.read())
        if is_effectively_empty_text(text):
            raise CodexOCRError(f"Codex OCR 未返回有效文本: {reference_path.name}")

    ocr_dir = ensure_directory(loaded_settings.path_for("ocr_dir"))
    sidecar_path = ocr_dir / f"{reference_path.stem}.codex_ocr.txt"
    sidecar_path.write_text(text, encoding="utf-8")
    return text, [f"PDF 文字层为空，已使用 Codex OCR fallback。model={configured_model or 'codex_default'}"]


def run_tesseract_pdf_ocr(reference_path: Path, loaded_settings: LoadedSettings) -> tuple[str, list[str]]:
    if shutil.which("ocrmypdf") is None:
        raise ReferencePreparationError("未找到 ocrmypdf，无法对扫描版 PDF 执行 OCR。")
    if shutil.which("tesseract") is None:
        raise ReferencePreparationError("未找到 tesseract，无法对扫描版 PDF 执行 OCR。")

    ocr_dir = ensure_directory(loaded_settings.path_for("ocr_dir"))
    ocr_pdf_path = ocr_dir / f"{reference_path.stem}.ocr.pdf"
    sidecar_path = ocr_dir / f"{reference_path.stem}.ocr.txt"

    if ocr_pdf_path.exists():
        ocr_pdf_path.unlink()
    if sidecar_path.exists():
        sidecar_path.unlink()

    command = [
        "ocrmypdf",
        "--skip-text",
        "--sidecar",
        str(sidecar_path),
        "-l",
        get_ocr_language_code(loaded_settings),
        str(reference_path),
        str(ocr_pdf_path),
    ]

    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ReferencePreparationError(f"OCR 命令执行失败: {reference_path.name} | {exc}") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise ReferencePreparationError(f"OCR 处理失败: {reference_path.name} | {stderr}")

    if not sidecar_path.exists():
        raise ReferencePreparationError(f"OCR 未生成 sidecar 文本: {reference_path.name}")

    text = sanitize_ocrmypdf_text(read_text_file(sidecar_path))
    sidecar_path.write_text(text, encoding="utf-8")
    warnings = ["PDF 文字层为空，已使用 OCR fallback。backend=ocrmypdf_tesseract"]
    if is_effectively_empty_text(text):
        warnings.append("OCR 结果为空或接近空，当前 PDF 可能质量较差。")

    return text, warnings


def read_txt_reference(reference_path: Path) -> tuple[str, str, list[str]]:
    return read_text_file(reference_path), "direct_text_read", []


def read_md_reference(reference_path: Path) -> tuple[str, str, list[str]]:
    return read_text_file(reference_path), "direct_markdown_read", []


def read_pdf_reference(reference_path: Path, loaded_settings: LoadedSettings) -> tuple[str, str, list[str]]:
    try:
        ocr_text, ocr_warnings = run_gemini_pdf_ocr(reference_path, loaded_settings)
        return ocr_text, "gemini_cli_pdf_ocr", ocr_warnings
    except GeminiOCRError as exc:
        extracted_text, warnings = extract_pdf_text(reference_path)
        if not is_effectively_empty_text(extracted_text):
            return (
                extracted_text,
                "pypdf_text_extract",
                [f"Gemini OCR 失败，已回退到 PDF 文字层提取。reason={exc}"] + warnings,
            )

        if not loaded_settings.settings.reference.run_ocr_when_needed:
            return (
                extracted_text,
                "pypdf_text_extract",
                [f"Gemini OCR 失败，且当前未启用 OCR fallback。reason={exc}"] + warnings,
            )

        try:
            ocr_text, ocr_warnings = run_codex_pdf_ocr(reference_path, loaded_settings)
            return (
                ocr_text,
                "codex_cli_pdf_ocr",
                [f"Gemini OCR 失败，已回退到 Codex OCR。reason={exc}"] + warnings + ocr_warnings,
            )
        except CodexOCRError as codex_exc:
            ocr_text, ocr_warnings = run_tesseract_pdf_ocr(reference_path, loaded_settings)
            return (
                ocr_text,
                "ocrmypdf_tesseract",
                [f"Gemini OCR 和 Codex OCR 都失败，已回退到 ocrmypdf。gemini_reason={exc}; codex_reason={codex_exc}"]
                + warnings
                + ocr_warnings,
            )


def prepare_reference_file(
    reference_path: Path,
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> ReferenceFileResult:
    source_type = reference_path.suffix.lower().lstrip(".")
    handlers: dict[str, Callable[[Path], tuple[str, str, list[str]]]] = {
        "txt": read_txt_reference,
        "md": read_md_reference,
    }
    handler = handlers.get(source_type)
    if source_type == "pdf":
        extracted_text, extraction_method, warnings = read_pdf_reference(reference_path, loaded_settings)
    elif handler is None:
        raise ReferencePreparationError(f"不支持的参考文件类型: {reference_path.name}")
    else:
        extracted_text, extraction_method, warnings = handler(reference_path)

    success = True
    if source_type == "pdf" and is_effectively_empty_text(extracted_text):
        success = False

    if logger:
        logger.info("参考文件处理完成 | %s | success=%s", reference_path.name, success)

    output_paths = build_reference_output_paths(
        reference_path,
        loaded_settings.path_for("extracted_text_dir"),
    )

    return ReferenceFileResult(
        source_file=build_source_file_label(reference_path, loaded_settings),
        source_type=source_type,
        output_text_file=output_paths.txt_path.name,
        extraction_method=extraction_method,
        success=success,
        text_length=len(extracted_text),
        warnings=warnings,
        extracted_text=extracted_text,
    )


def write_reference_result(result: ReferenceFileResult, output_paths: ReferenceOutputPaths) -> None:
    ensure_directory(output_paths.txt_path.parent)

    if result.success:
        with output_paths.txt_path.open("w", encoding="utf-8") as file:
            file.write(result.extracted_text)

    payload = {
        "source_file": result.source_file,
        "source_type": result.source_type,
        "output_text_file": result.output_text_file,
        "extraction_method": result.extraction_method,
        "success": result.success,
        "text_length": result.text_length,
        "warnings": result.warnings,
    }
    with output_paths.json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def prepare_reference_batch(
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> ReferenceBatchSummary:
    reference_dir = loaded_settings.path_for("reference_dir")
    output_dir = ensure_directory(loaded_settings.path_for("extracted_text_dir"))
    allowed_extensions = get_supported_reference_extensions(loaded_settings)
    reference_files = iter_reference_files(reference_dir, allowed_extensions)

    if not reference_files:
        supported_ext = ", ".join(allowed_extensions)
        raise ReferenceInputEmptyError(
            f"输入目录中没有可处理的参考文件: {reference_dir}。支持扩展名: {supported_ext}"
        )

    items: list[ReferenceBatchItem] = []
    success_count = 0
    skipped_count = 0
    failed_count = 0

    for reference_path in reference_files:
        output_paths = build_reference_output_paths(reference_path, output_dir)
        result = prepare_reference_file(reference_path, loaded_settings, logger=logger)
        write_reference_result(result, output_paths)

        if result.success:
            success_count += 1
        elif result.source_type == "pdf":
            skipped_count += 1
        else:
            failed_count += 1

        items.append(
            ReferenceBatchItem(
                source_path=reference_path,
                output_paths=output_paths,
                success=result.success,
                warnings=result.warnings,
            )
        )

    return ReferenceBatchSummary(
        total=len(reference_files),
        success=success_count,
        skipped=skipped_count,
        failed=failed_count,
        items=items,
    )


def summarize_reference_results(summary: ReferenceBatchSummary) -> str:
    return (
        f"total={summary.total}, success={summary.success}, "
        f"skipped={summary.skipped}, failed={summary.failed}"
    )
