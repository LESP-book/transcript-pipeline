from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from src.runtime_utils import ensure_directory, relativize_path
from src.schemas import LoadedSettings

PROMPT_MISSING_ERROR = "缺少阶段 6 提示词配置，请检查 prompts.classify_and_correct"
BACKEND_CODEX = "codex_cli"
BACKEND_GEMINI = "gemini_cli"
BACKEND_FALLBACK = "local_fallback"


class RefinementError(RuntimeError):
    """Raised when refinement fails."""


class RefinementInputEmptyError(RefinementError):
    """Raised when there are no classified files to refine."""


class PromptLoadError(RefinementError):
    """Raised when prompt files cannot be loaded."""


class CLIBackendError(RefinementError):
    """Raised when a local CLI backend fails."""


class CLIBackendRetryableError(CLIBackendError):
    """Raised when a local CLI backend fails in a retryable way."""


@dataclass(frozen=True)
class RefinementInputPaths:
    basename: str
    asr_text_path: Path
    reference_text_path: Path


@dataclass(frozen=True)
class BackendDocumentRefinementResult:
    backend: str
    model_name: str
    final_markdown: str
    refinement_strategy: str
    refinement_reason: str
    needs_review_sections: list[dict[str, Any]]
    refinement_notes: list[str]


@dataclass(frozen=True)
class RefinementOutputPath:
    json_path: Path


@dataclass(frozen=True)
class RefinementBatchItem:
    basename: str
    output_path: Path | None
    success: bool
    skipped: bool
    selected_backends: list[str]
    reason: str | None = None


@dataclass(frozen=True)
class RefinementBatchSummary:
    total: int
    success: int
    skipped: int
    failed: int
    backends: list[str]
    items: list[RefinementBatchItem]


def iter_asr_text_files(asr_dir: Path) -> list[Path]:
    if not asr_dir.exists():
        return []
    return sorted(path for path in asr_dir.iterdir() if path.is_file() and path.suffix.lower() == ".txt")


def build_refinement_output_path(asr_text_path: Path, output_dir: Path) -> RefinementOutputPath:
    return RefinementOutputPath(json_path=output_dir / f"{asr_text_path.stem}.json")


def normalize_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_multiline_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if not line:
            if buffer:
                paragraphs.append(" ".join(buffer).strip())
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        paragraphs.append(" ".join(buffer).strip())
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph).strip()


def markdown_to_plain_text(markdown_text: str) -> str:
    lines: list[str] = []
    in_code_block = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
        if not stripped:
            lines.append("")
            continue
        lines.append(stripped)
    return normalize_multiline_text("\n".join(lines))


def truncate_for_prompt(text: str, max_chars: int) -> str:
    normalized = normalize_inline_text(text)
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    if max_chars <= 1:
        return normalized[:max_chars]
    return f"{normalized[: max_chars - 1]}…"


def strip_markdown_fence(text: str) -> str:
    fenced = text.strip()
    if fenced.startswith("```"):
        fenced = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", fenced)
        fenced = re.sub(r"\n?```$", "", fenced)
    return fenced.strip()


def extract_json_payload(text: str) -> dict[str, Any]:
    candidate = strip_markdown_fence(text)
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise CLIBackendError("CLI 输出中未找到可解析的 JSON 对象。")

    try:
        parsed = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise CLIBackendError(f"CLI 输出中的 JSON 解析失败: {exc}") from exc

    if not isinstance(parsed, dict):
        raise CLIBackendError("CLI 输出的 JSON 顶层必须是对象。")
    return parsed


def load_refinement_prompt(loaded_settings: LoadedSettings) -> str:
    prompts = loaded_settings.settings.prompts
    if prompts is None or not prompts.classify_and_correct:
        raise PromptLoadError(PROMPT_MISSING_ERROR)

    prompt_path = loaded_settings.resolve_path(prompts.classify_and_correct)
    if not prompt_path.exists():
        raise PromptLoadError(f"阶段 6 提示词文件不存在: {prompt_path}")

    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PromptLoadError(f"无法读取阶段 6 提示词文件: {prompt_path} | {exc}") from exc


def resolve_refinement_input_paths(loaded_settings: LoadedSettings, asr_text_path: Path) -> RefinementInputPaths:
    basename = asr_text_path.stem
    asr_text_path = loaded_settings.path_for("asr_dir") / f"{basename}.txt"
    reference_text_path = loaded_settings.path_for("extracted_text_dir") / f"{basename}.txt"

    if not asr_text_path.exists():
        raise RefinementError(f"阶段 6 缺少对应 ASR 文本文件: {asr_text_path}")
    if not reference_text_path.exists():
        raise RefinementError(f"阶段 6 缺少对应参考原文文件: {reference_text_path}")

    return RefinementInputPaths(
        basename=basename,
        asr_text_path=asr_text_path,
        reference_text_path=reference_text_path,
    )


def load_text_file(path: Path, label: str) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RefinementError(f"无法读取{label}文件: {path} | {exc}") from exc

    if not text:
        raise RefinementError(f"{label}文件为空: {path}")
    return text


def build_fulltext_refine_prompt(
    prompt_text: str,
    input_paths: RefinementInputPaths,
    *,
    asr_full_text: str,
    reference_full_text: str,
) -> str:
    sections = [
        prompt_text.strip(),
        "",
        f"当前文件: {input_paths.basename}.txt",
        "下面提供录音转写文本和参考原文，请直接按要求输出最终 Markdown 的 JSON 结果。",
    ]
    sections.extend(
        [
            "",
            "录音转写文本：",
            asr_full_text,
            "",
            "参考原文：",
            reference_full_text,
        ]
    )
    return "\n".join(sections).strip()


def run_subprocess(command: list[str], *, prompt: str, cwd: Path, timeout_seconds: int) -> str:
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=str(cwd),
            timeout=timeout_seconds,
            check=False,
        )
    except OSError as exc:
        raise CLIBackendError(f"CLI 命令启动失败: {' '.join(command)} | {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CLIBackendError(f"CLI 命令执行超时: {' '.join(command)}") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        error_message = f"CLI 命令执行失败: {' '.join(command)} | {stderr}"
        if is_gemini_capacity_error(stderr):
            raise CLIBackendRetryableError(error_message)
        raise CLIBackendError(error_message)

    output = completed.stdout.strip()
    if not output:
        raise CLIBackendError(f"CLI 命令没有返回内容: {' '.join(command)}")
    return output


def is_gemini_capacity_error(text: str) -> bool:
    normalized = text.upper()
    return "429" in normalized or "MODEL_CAPACITY_EXHAUSTED" in normalized or "RESOURCE_EXHAUSTED" in normalized


def parse_backend_document_result(backend: str, payload: dict[str, Any]) -> BackendDocumentRefinementResult:
    final_markdown = str(payload.get("final_markdown", "")).strip()
    if not final_markdown:
        # 向后兼容旧结果，避免单个后端仍返回旧字段时整批失败。
        legacy_full_text = normalize_multiline_text(str(payload.get("refined_full_text", "")).strip())
        if legacy_full_text:
            final_markdown = legacy_full_text
    if not final_markdown:
        raise CLIBackendError("CLI 返回结构无效：缺少 final_markdown。")
    plain_text = markdown_to_plain_text(final_markdown)

    raw_review_sections = payload.get("needs_review_sections", [])
    needs_review_sections: list[dict[str, Any]] = []
    if isinstance(raw_review_sections, list):
        for item in raw_review_sections:
            if not isinstance(item, dict):
                continue
            excerpt = normalize_inline_text(str(item.get("excerpt", "")).strip())
            reason = normalize_inline_text(str(item.get("reason", "")).strip())
            if not excerpt and not reason:
                continue
            needs_review_sections.append(
                {
                    "excerpt": excerpt or truncate_for_prompt(plain_text, 80),
                    "reason": reason or f"{backend}_needs_review",
                }
            )

    raw_notes = payload.get("refinement_notes", [])
    refinement_notes = [
        normalize_inline_text(str(item).strip())
        for item in raw_notes
        if normalize_inline_text(str(item).strip())
    ] if isinstance(raw_notes, list) else []

    return BackendDocumentRefinementResult(
        backend=backend,
        model_name=str(payload.get("model_name", "")).strip(),
        final_markdown=final_markdown,
        refinement_strategy=str(payload.get("refinement_strategy", f"{backend}_fulltext_refine")),
        refinement_reason=str(payload.get("refinement_reason", f"{backend}_refinement")),
        needs_review_sections=needs_review_sections,
        refinement_notes=refinement_notes,
    )


def run_codex_cli(prompt: str, loaded_settings: LoadedSettings) -> BackendDocumentRefinementResult:
    llm_settings = loaded_settings.settings.llm
    timeout_seconds = llm_settings.timeout_seconds
    configured_model = llm_settings.model.strip()
    configured_reasoning_effort = llm_settings.reasoning_effort.strip()
    with tempfile.NamedTemporaryFile("r+", encoding="utf-8", suffix=".txt", delete=True) as output_file:
        command = [
            "codex",
            "exec",
            "-C",
            str(loaded_settings.project_root),
            "-s",
            "read-only",
        ]
        if configured_model:
            command.extend(["-m", configured_model])
        if configured_reasoning_effort:
            command.extend(["-c", f'model_reasoning_effort="{configured_reasoning_effort}"'])
        command.extend(["-o", output_file.name, "-"])
        run_subprocess(command, prompt=prompt, cwd=loaded_settings.project_root, timeout_seconds=timeout_seconds)
        output_file.seek(0)
        payload = extract_json_payload(output_file.read())

    result = parse_backend_document_result(BACKEND_CODEX, payload)
    if result.model_name:
        return result
    return BackendDocumentRefinementResult(
        backend=result.backend,
        model_name=configured_model or "codex_default",
        final_markdown=result.final_markdown,
        refinement_strategy=result.refinement_strategy,
        refinement_reason=result.refinement_reason,
        needs_review_sections=result.needs_review_sections,
        refinement_notes=result.refinement_notes,
    )


def run_gemini_cli(prompt: str, loaded_settings: LoadedSettings) -> BackendDocumentRefinementResult:
    llm_settings = loaded_settings.settings.llm
    models_to_try = [llm_settings.gemini_model]
    fallback_model = llm_settings.gemini_fallback_model.strip()
    if fallback_model and fallback_model not in models_to_try:
        models_to_try.append(fallback_model)

    last_error: CLIBackendError | None = None
    for index, model_name in enumerate(models_to_try):
        command = ["gemini", "-m", model_name, "-p", prompt]
        try:
            output = run_subprocess(
                command,
                prompt="",
                cwd=loaded_settings.project_root,
                timeout_seconds=llm_settings.timeout_seconds,
            )
            payload = extract_json_payload(output)
            result = parse_backend_document_result(BACKEND_GEMINI, payload)
            if result.model_name:
                return result
            return BackendDocumentRefinementResult(
                backend=result.backend,
                model_name=model_name,
                final_markdown=result.final_markdown,
                refinement_strategy=result.refinement_strategy,
                refinement_reason=result.refinement_reason,
                needs_review_sections=result.needs_review_sections,
                refinement_notes=result.refinement_notes,
            )
        except CLIBackendRetryableError as exc:
            last_error = exc
            if index == len(models_to_try) - 1:
                break
            continue
        except CLIBackendError as exc:
            last_error = exc
            break

    if last_error is not None:
        raise last_error
    raise CLIBackendError("Gemini CLI 调用失败，未获得可用结果。")


def run_backend_cli(backend: str, prompt: str, loaded_settings: LoadedSettings) -> BackendDocumentRefinementResult:
    if backend == BACKEND_CODEX:
        return run_codex_cli(prompt, loaded_settings)
    if backend == BACKEND_GEMINI:
        return run_gemini_cli(prompt, loaded_settings)
    raise CLIBackendError(f"未知阶段 6 后端: {backend}")


def build_fallback_document_result(title: str, asr_full_text: str) -> BackendDocumentRefinementResult:
    review_sections = []
    paragraphs = [item.strip() for item in asr_full_text.splitlines() if item.strip()]
    for paragraph in paragraphs[:5]:
        excerpt = truncate_for_prompt(paragraph, 80)
        if excerpt:
            review_sections.append({"excerpt": excerpt, "reason": "fallback_review_from_asr"})

    final_markdown = f"# {title}\n\n{normalize_multiline_text(asr_full_text)}".strip()

    return BackendDocumentRefinementResult(
        backend=BACKEND_FALLBACK,
        model_name=BACKEND_FALLBACK,
        final_markdown=final_markdown,
        refinement_strategy="keep_asr_full_text",
        refinement_reason="preserve_original_wording_for_safe_fallback",
        needs_review_sections=review_sections,
        refinement_notes=["all_cli_backends_failed_use_fallback"],
    )


def calculate_document_score(
    *,
    asr_full_text: str,
    reference_full_text: str,
    result: BackendDocumentRefinementResult,
) -> float:
    refined_text = normalize_inline_text(markdown_to_plain_text(result.final_markdown))
    asr_similarity = fuzz.ratio(refined_text, normalize_inline_text(asr_full_text)) if asr_full_text else 0.0
    reference_similarity = fuzz.ratio(refined_text, normalize_inline_text(reference_full_text)) if reference_full_text else 0.0
    reference_weight = 0.6 if reference_full_text else 0.0
    asr_weight = 1.0 - reference_weight
    penalty = min(len(result.needs_review_sections), 5) * 2.0
    return round(asr_similarity * asr_weight + reference_similarity * reference_weight - penalty, 2)


def compare_backend_documents(
    *,
    asr_full_text: str,
    reference_full_text: str,
    candidates: list[BackendDocumentRefinementResult],
) -> tuple[BackendDocumentRefinementResult, str]:
    if len(candidates) == 1 and candidates[0].backend == BACKEND_FALLBACK:
        return candidates[0], "all_cli_backends_failed_use_fallback"

    scored = [
        (calculate_document_score(asr_full_text=asr_full_text, reference_full_text=reference_full_text, result=result), result)
        for result in candidates
        if result.final_markdown
    ]
    if not scored:
        fallback = build_fallback_document_result("未命名讲解", asr_full_text)
        return fallback, "no_cli_result_available_use_fallback"

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_result = scored[0]
    if len(scored) == 1:
        return best_result, f"single_backend_selected:{best_result.backend}:{best_score}"

    second_score, second_result = scored[1]
    return best_result, f"selected={best_result.backend}:{best_score};runner_up={second_result.backend}:{second_score}"


def write_refinement_result(
    *,
    input_paths: RefinementInputPaths,
    loaded_settings: LoadedSettings,
    backend_status: dict[str, str],
    selected_result: BackendDocumentRefinementResult,
    comparison_summary: str,
    output_path: RefinementOutputPath,
) -> None:
    ensure_directory(output_path.json_path.parent)
    payload = {
        "source_asr_file": relativize_path(input_paths.asr_text_path, loaded_settings.project_root),
        "source_reference_file": relativize_path(input_paths.reference_text_path, loaded_settings.project_root),
        "refinement_backends": list(loaded_settings.settings.llm.backends),
        "backend_status": backend_status,
        "prompt_mode": "fulltext_final_markdown",
        "selected_backend": selected_result.backend,
        "comparison_summary": comparison_summary,
        "final_markdown": selected_result.final_markdown,
        "refined_full_text": markdown_to_plain_text(selected_result.final_markdown),
        "refinement_strategy": selected_result.refinement_strategy,
        "refinement_reason": selected_result.refinement_reason,
        "needs_review_sections": selected_result.needs_review_sections,
        "refinement_notes": selected_result.refinement_notes,
    }
    with output_path.json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def refine_batch(
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> RefinementBatchSummary:
    asr_dir = loaded_settings.path_for("asr_dir")
    output_dir = ensure_directory(loaded_settings.path_for("refined_dir"))
    asr_files = iter_asr_text_files(asr_dir)

    if not asr_files:
        raise RefinementInputEmptyError(f"ASR 输入目录中没有可处理的 TXT 文件: {asr_dir}")

    prompt_text = load_refinement_prompt(loaded_settings)
    items: list[RefinementBatchItem] = []
    success_count = 0

    for asr_text_path in asr_files:
        input_paths = resolve_refinement_input_paths(loaded_settings, asr_text_path)
        asr_full_text = load_text_file(input_paths.asr_text_path, "ASR")
        reference_full_text = load_text_file(input_paths.reference_text_path, "参考原文")
        prompt = build_fulltext_refine_prompt(
            prompt_text,
            input_paths,
            asr_full_text=asr_full_text,
            reference_full_text=reference_full_text,
        )

        backend_results: list[BackendDocumentRefinementResult] = []
        backend_status: dict[str, str] = {}
        document_title = input_paths.basename
        for backend in loaded_settings.settings.llm.backends:
            try:
                result = run_backend_cli(backend, prompt, loaded_settings)
            except CLIBackendError as exc:
                backend_status[backend] = "failed_on_file"
                if logger:
                    logger.warning("阶段 6 后端失败 | backend=%s | file=%s | %s", backend, input_paths.basename, exc)
                continue

            backend_results.append(result)
            status = "returned_fulltext"
            if result.model_name:
                status = f"{status}:model={result.model_name}"
            backend_status[backend] = status

        if not backend_results and loaded_settings.settings.llm.enable_fallback:
            backend_results = [build_fallback_document_result(document_title, asr_full_text)]
            backend_status["fallback"] = "used"

        if not backend_results:
            raise CLIBackendError(f"阶段 6 所有后端均未返回结果，且未启用 fallback: {input_paths.basename}.txt")

        selected_result, comparison_summary = compare_backend_documents(
            asr_full_text=asr_full_text,
            reference_full_text=reference_full_text,
            candidates=backend_results,
        )
        output_path = build_refinement_output_path(asr_text_path, output_dir)
        write_refinement_result(
            input_paths=input_paths,
            loaded_settings=loaded_settings,
            backend_status=backend_status,
            selected_result=selected_result,
            comparison_summary=comparison_summary,
            output_path=output_path,
        )

        items.append(
            RefinementBatchItem(
                basename=input_paths.basename,
                output_path=output_path.json_path,
                success=True,
                skipped=False,
                selected_backends=[selected_result.backend],
            )
        )
        success_count += 1
        if logger:
            logger.info(
                "精修完成 | %s | prompt_mode=fulltext_final_markdown | needs_review=%s | selected_backend=%s",
                input_paths.basename,
                len(selected_result.needs_review_sections),
                selected_result.backend,
            )

    return RefinementBatchSummary(
        total=len(asr_files),
        success=success_count,
        skipped=0,
        failed=0,
        backends=list(loaded_settings.settings.llm.backends),
        items=items,
    )


def summarize_refinement_results(summary: RefinementBatchSummary) -> str:
    return (
        f"total={summary.total}, success={summary.success}, skipped={summary.skipped}, "
        f"failed={summary.failed}, backends={','.join(summary.backends)}"
    )
