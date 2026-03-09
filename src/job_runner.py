from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

from scripts.run_pipeline import run_stage
from src.config_loader import ConfigLoadError, load_settings
from src.glossary_utils import build_initial_prompt, load_glossary_terms, merge_glossary_terms
from src.runtime_utils import ensure_directory, normalize_stage_name, relativize_path, setup_logging
from src.schemas import LoadedSettings

CANONICAL_INPUT_BASENAME = "source"
WEB_REQUEST_TIMEOUT_SECONDS = 60


class JobRunnerError(RuntimeError):
    """Raised when a single-run job cannot be prepared or executed."""


@dataclass(frozen=True)
class JobPaths:
    job_id: str
    job_root: Path
    input_videos_dir: Path
    input_reference_dir: Path
    intermediate_audio_dir: Path
    intermediate_asr_dir: Path
    intermediate_ocr_dir: Path
    intermediate_extracted_text_dir: Path
    intermediate_refined_dir: Path
    output_final_dir: Path
    manifest_path: Path
    settings_path: Path


@dataclass(frozen=True)
class JobPreparedInputs:
    video_path: Path
    reference_path: Path
    reference_type: str


@dataclass(frozen=True)
class JobResult:
    job_id: str
    job_root: Path
    generated_settings_path: Path
    final_markdown_path: Path
    copied_output_path: Path


def resolve_common_glossary_path(project_root: Path) -> Path:
    return project_root / "config/glossaries/marxism_common.txt"


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._ignored_tags = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag in {"script", "style", "noscript"}:
            self._ignored_tags += 1
        elif tag in {"p", "br", "div", "article", "section", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_tags > 0:
            self._ignored_tags -= 1
        elif tag in {"p", "div", "article", "section", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_tags:
            return
        stripped = data.strip()
        if stripped:
            self._chunks.append(stripped)

    def get_text(self) -> str:
        raw_text = " ".join(self._chunks)
        normalized = re.sub(r"[ \t]+", " ", raw_text)
        normalized = re.sub(r"\n\s*\n+", "\n\n", normalized)
        return normalized.strip()


def is_url_reference(reference_source: str) -> bool:
    parsed = urlparse(reference_source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def sanitize_filename_stem(name: str) -> str:
    sanitized = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    return sanitized or CANONICAL_INPUT_BASENAME


def create_job_id() -> str:
    return uuid.uuid4().hex[:12]


def build_job_paths(project_root: Path, job_id: str) -> JobPaths:
    job_root = ensure_directory(project_root / "data/jobs" / job_id)
    input_dir = ensure_directory(job_root / "input")
    intermediate_dir = ensure_directory(job_root / "intermediate")
    output_dir = ensure_directory(job_root / "output")

    return JobPaths(
        job_id=job_id,
        job_root=job_root,
        input_videos_dir=ensure_directory(input_dir / "videos"),
        input_reference_dir=ensure_directory(input_dir / "reference"),
        intermediate_audio_dir=ensure_directory(intermediate_dir / "audio"),
        intermediate_asr_dir=ensure_directory(intermediate_dir / "asr"),
        intermediate_ocr_dir=ensure_directory(intermediate_dir / "ocr"),
        intermediate_extracted_text_dir=ensure_directory(intermediate_dir / "extracted_text"),
        intermediate_refined_dir=ensure_directory(intermediate_dir / "refined"),
        output_final_dir=ensure_directory(output_dir / "final"),
        manifest_path=job_root / "manifest.json",
        settings_path=job_root / "settings.generated.yaml",
    )


def detect_reference_source_type(reference_source: str | Path) -> str:
    candidate = str(reference_source)
    if is_url_reference(candidate):
        return "url"

    path = Path(candidate)
    extension = path.suffix.lower()
    if extension == ".txt":
        return "txt"
    if extension == ".md":
        return "md"
    if extension == ".pdf":
        return "pdf"
    raise JobRunnerError(f"不支持的参考源类型: {reference_source}。当前支持网页链接、txt、md、pdf。")


def copy_local_reference(reference_path: Path, destination_path: Path) -> Path:
    if not reference_path.exists():
        raise JobRunnerError(f"参考源不存在: {reference_path}")
    ensure_directory(destination_path.parent)
    shutil.copy2(reference_path, destination_path)
    return destination_path


def fetch_reference_from_url(reference_url: str, destination_dir: Path, basename: str) -> tuple[Path, str]:
    request = Request(reference_url, headers={"User-Agent": "transcript-pipeline/0.1"})
    try:
        with urlopen(request, timeout=WEB_REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            payload = response.read()
    except OSError as exc:
        raise JobRunnerError(f"网页参考抓取失败: {reference_url} | {exc}") from exc

    if content_type == "application/pdf" or reference_url.lower().endswith(".pdf"):
        output_path = destination_dir / f"{basename}.pdf"
        output_path.write_bytes(payload)
        return output_path, "url_pdf"

    text = payload.decode(charset, errors="ignore")
    extractor = HTMLTextExtractor()
    extractor.feed(text)
    extracted_text = extractor.get_text()
    if not extracted_text:
        raise JobRunnerError(f"网页参考提取失败，未得到可用正文: {reference_url}")

    output_path = destination_dir / f"{basename}.txt"
    output_path.write_text(extracted_text, encoding="utf-8")
    return output_path, "url_text"


def prepare_job_inputs(
    *,
    video_source: Path,
    reference_source: str,
    job_paths: JobPaths,
) -> JobPreparedInputs:
    if not video_source.exists():
        raise JobRunnerError(f"视频源不存在: {video_source}")

    video_destination = job_paths.input_videos_dir / f"{CANONICAL_INPUT_BASENAME}{video_source.suffix.lower()}"
    shutil.copy2(video_source, video_destination)

    reference_type = detect_reference_source_type(reference_source)
    if reference_type == "url":
        reference_destination, resolved_reference_type = fetch_reference_from_url(
            reference_source,
            job_paths.input_reference_dir,
            CANONICAL_INPUT_BASENAME,
        )
        return JobPreparedInputs(
            video_path=video_destination,
            reference_path=reference_destination,
            reference_type=resolved_reference_type,
        )

    local_reference_path = Path(reference_source)
    reference_destination = job_paths.input_reference_dir / f"{CANONICAL_INPUT_BASENAME}{local_reference_path.suffix.lower()}"
    return JobPreparedInputs(
        video_path=video_destination,
        reference_path=copy_local_reference(local_reference_path, reference_destination),
        reference_type=reference_type,
    )


def load_raw_settings(loaded_settings: LoadedSettings) -> dict[str, Any]:
    try:
        with loaded_settings.settings_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise JobRunnerError(f"无法读取原始配置文件: {loaded_settings.settings_path} | {exc}") from exc
    except yaml.YAMLError as exc:
        raise JobRunnerError(f"原始配置 YAML 解析失败: {loaded_settings.settings_path} | {exc}") from exc

    if not isinstance(payload, dict):
        raise JobRunnerError(f"原始配置结构无效: {loaded_settings.settings_path}")
    return payload


def build_job_initial_prompt(
    *,
    project_root: Path,
    glossary_file: str | None,
    book_name: str | None,
    chapter: str | None,
    max_chars: int = 400,
) -> str:
    common_terms = load_glossary_terms(resolve_common_glossary_path(project_root))
    extra_terms = load_glossary_terms(Path(glossary_file).expanduser().resolve()) if glossary_file else []
    title_terms = [term for term in [book_name or "", chapter or ""] if term.strip()]
    merged_terms = merge_glossary_terms(title_terms, extra_terms, common_terms)
    return build_initial_prompt(merged_terms, max_chars=max_chars)


def write_job_settings(
    *,
    project_root: Path,
    loaded_settings: LoadedSettings,
    job_paths: JobPaths,
    profile_name: str,
    glossary_file: str | None = None,
    book_name: str | None = None,
    chapter: str | None = None,
) -> Path:
    payload = load_raw_settings(loaded_settings)
    payload.setdefault("runtime", {})
    payload["runtime"]["profile"] = profile_name
    payload.setdefault("asr", {})
    payload["asr"]["initial_prompt"] = build_job_initial_prompt(
        project_root=project_root,
        glossary_file=glossary_file,
        book_name=book_name,
        chapter=chapter,
    )

    payload["paths"] = {
        "videos_dir": str(job_paths.input_videos_dir),
        "audio_dir": str(job_paths.job_root / "input/audio"),
        "reference_dir": str(job_paths.input_reference_dir),
        "asr_dir": str(job_paths.intermediate_asr_dir),
        "ocr_dir": str(job_paths.intermediate_ocr_dir),
        "extracted_text_dir": str(job_paths.intermediate_extracted_text_dir),
        "chunks_dir": str(job_paths.job_root / "intermediate/chunks"),
        "aligned_dir": str(job_paths.job_root / "intermediate/aligned"),
        "classified_dir": str(job_paths.job_root / "intermediate/classified"),
        "refined_dir": str(job_paths.intermediate_refined_dir),
        "review_dir": str(job_paths.job_root / "output/review"),
        "final_dir": str(job_paths.output_final_dir),
        "logs_dir": str(job_paths.job_root / "output/logs"),
    }

    prompts = payload.get("prompts", {})
    if isinstance(prompts, dict):
        for key, value in list(prompts.items()):
            prompts[key] = str(loaded_settings.resolve_path(str(value)))
        payload["prompts"] = prompts

    try:
        job_paths.settings_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except OSError as exc:
        raise JobRunnerError(f"无法写入 job 配置文件: {job_paths.settings_path} | {exc}") from exc

    return job_paths.settings_path


def write_job_manifest(
    *,
    loaded_settings: LoadedSettings,
    job_paths: JobPaths,
    prepared_inputs: JobPreparedInputs,
    video_source: Path,
    reference_source: str,
    output_dir: Path,
    profile_name: str,
    book_name: str | None,
    chapter: str | None,
    glossary_file: str | None,
) -> None:
    payload = {
        "job_id": job_paths.job_id,
        "profile": profile_name,
        "video_source": str(video_source.resolve()),
        "reference_source": reference_source,
        "reference_type": prepared_inputs.reference_type,
        "prepared_video": relativize_path(prepared_inputs.video_path, loaded_settings.project_root),
        "prepared_reference": relativize_path(prepared_inputs.reference_path, loaded_settings.project_root),
        "output_dir": str(output_dir.resolve()),
        "book_name": book_name or "",
        "chapter": chapter or "",
        "glossary_file": str(Path(glossary_file).expanduser().resolve()) if glossary_file else "",
        "generated_settings_path": relativize_path(job_paths.settings_path, loaded_settings.project_root),
    }
    job_paths.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_final_output_filename(video_source: Path, *, book_name: str | None, chapter: str | None) -> str:
    if book_name and chapter:
        return f"《{sanitize_filename_stem(book_name)}》{sanitize_filename_stem(chapter)}.md"
    if book_name:
        return f"《{sanitize_filename_stem(book_name)}》.md"
    if chapter:
        return f"{sanitize_filename_stem(chapter)}.md"
    return f"{sanitize_filename_stem(video_source.stem)}.md"


def copy_final_output(job_paths: JobPaths, output_dir: Path, final_filename: str) -> tuple[Path, Path]:
    final_candidates = sorted(job_paths.output_final_dir.glob("*.md"))
    if not final_candidates:
        raise JobRunnerError(f"job 未生成最终 Markdown 输出: {job_paths.output_final_dir}")

    source_path = final_candidates[0]
    ensure_directory(output_dir)
    destination_path = output_dir / final_filename
    shutil.copy2(source_path, destination_path)
    return source_path, destination_path


def run_job_pipeline(loaded_settings: LoadedSettings, logger: logging.Logger) -> None:
    raw_stages = loaded_settings.settings.pipeline.stages if loaded_settings.settings.pipeline else []
    if not raw_stages:
        raise JobRunnerError("当前配置未定义主链阶段列表。")

    stages = [normalize_stage_name(stage_name) for stage_name in raw_stages]
    logger.info("job 主链启动 | profile=%s | stages=%s", loaded_settings.active_profile_name, ",".join(stages))
    for stage_name in stages:
        logger.info("job 主链执行 | stage=%s", stage_name)
        exit_code = run_stage(stage_name, loaded_settings, logger)
        if exit_code != 0:
            raise JobRunnerError(f"job 主链失败: stage={stage_name} exit_code={exit_code}")


def run_single_job(
    *,
    project_root: Path,
    base_loaded_settings: LoadedSettings,
    video: str,
    reference: str,
    output_dir: str,
    profile: str | None = None,
    book_name: str | None = None,
    chapter: str | None = None,
    glossary_file: str | None = None,
) -> JobResult:
    video_source = Path(video).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    profile_name = profile or base_loaded_settings.active_profile_name
    job_id = create_job_id()
    job_paths = build_job_paths(project_root, job_id)
    prepared_inputs = prepare_job_inputs(
        video_source=video_source,
        reference_source=reference,
        job_paths=job_paths,
    )

    generated_settings_path = write_job_settings(
        project_root=project_root,
        loaded_settings=base_loaded_settings,
        job_paths=job_paths,
        profile_name=profile_name,
        glossary_file=glossary_file,
        book_name=book_name,
        chapter=chapter,
    )
    write_job_manifest(
        loaded_settings=base_loaded_settings,
        job_paths=job_paths,
        prepared_inputs=prepared_inputs,
        video_source=video_source,
        reference_source=reference,
        output_dir=output_path,
        profile_name=profile_name,
        book_name=book_name,
        chapter=chapter,
        glossary_file=glossary_file,
    )

    try:
        job_loaded_settings = load_settings(
            settings_path=generated_settings_path,
            profile_name=profile_name,
            project_root=project_root,
        )
    except ConfigLoadError as exc:
        raise JobRunnerError(f"job 配置加载失败: {generated_settings_path} | {exc}") from exc

    logger = setup_logging(job_loaded_settings.settings.runtime.log_level)
    logger.info("job 启动 | job_id=%s | reference_type=%s", job_id, prepared_inputs.reference_type)
    run_job_pipeline(job_loaded_settings, logger)

    final_source_path, copied_output_path = copy_final_output(
        job_paths,
        output_path,
        build_final_output_filename(video_source, book_name=book_name, chapter=chapter),
    )
    logger.info("job 完成 | job_id=%s | final=%s", job_id, copied_output_path)

    return JobResult(
        job_id=job_id,
        job_root=job_paths.job_root,
        generated_settings_path=generated_settings_path,
        final_markdown_path=final_source_path,
        copied_output_path=copied_output_path,
    )
