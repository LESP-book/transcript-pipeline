from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from src.runtime_utils import ensure_directory
from src.schemas import LoadedSettings

MIN_EXTRACTED_PDF_TEXT_LENGTH = 10


class ReferencePreparationError(RuntimeError):
    """Raised when reference preparation fails."""


class ReferenceInputEmptyError(ReferencePreparationError):
    """Raised when there are no supported reference files to process."""


class PdfDependencyError(ReferencePreparationError):
    """Raised when PDF extraction dependencies are missing."""


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
    if not text or len(text.replace("\n", "").strip()) < MIN_EXTRACTED_PDF_TEXT_LENGTH:
        warnings.append("PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。")

    return text, warnings


def read_txt_reference(reference_path: Path) -> tuple[str, str, list[str]]:
    return read_text_file(reference_path), "direct_text_read", []


def read_md_reference(reference_path: Path) -> tuple[str, str, list[str]]:
    return read_text_file(reference_path), "direct_markdown_read", []


def read_pdf_reference(reference_path: Path) -> tuple[str, str, list[str]]:
    extracted_text, warnings = extract_pdf_text(reference_path)
    return extracted_text, "pypdf_text_extract", warnings


def prepare_reference_file(
    reference_path: Path,
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> ReferenceFileResult:
    source_type = reference_path.suffix.lower().lstrip(".")
    handlers: dict[str, Callable[[Path], tuple[str, str, list[str]]]] = {
        "txt": read_txt_reference,
        "md": read_md_reference,
        "pdf": read_pdf_reference,
    }
    handler = handlers.get(source_type)
    if handler is None:
        raise ReferencePreparationError(f"不支持的参考文件类型: {reference_path.name}")
    extracted_text, extraction_method, warnings = handler(reference_path)

    success = True
    if source_type == "pdf" and warnings and not extracted_text.strip():
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
