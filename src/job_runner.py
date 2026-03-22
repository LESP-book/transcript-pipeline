from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class BatchJobSpec:
    video: str
    reference: str
    output_dir: str
    mode: str
    book_name: str | None = None
    chapter: str | None = None
    glossary_file: str | None = None


@dataclass
class BatchJobRuntime:
    job_id: str
    job_root: Path
    spec: BatchJobSpec
    status: str = "pending"
    failed_stage: str | None = None
    error_message: str | None = None
    copied_output_path: Path | None = None


@dataclass(frozen=True)
class BatchRunSummary:
    batch_id: str
    total: int
    success: int
    failed: int
    items: list[BatchJobRuntime] = field(default_factory=list)


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


def create_batch_id() -> str:
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


def build_batch_root(project_root: Path, batch_id: str) -> Path:
    return ensure_directory(project_root / "data/jobs/batches" / batch_id)


def supported_video_extensions(loaded_settings: LoadedSettings) -> set[str]:
    return {extension.lower() for extension in loaded_settings.settings.audio.supported_video_ext}


def supported_reference_extensions() -> tuple[str, ...]:
    return (".txt", ".md", ".pdf")


def build_failed_batch_runtime(
    *,
    spec: BatchJobSpec,
    error_message: str,
    failed_stage: str,
    job_id: str = "",
    job_root: Path | None = None,
) -> BatchJobRuntime:
    return BatchJobRuntime(
        job_id=job_id,
        job_root=job_root or Path(),
        spec=spec,
        status="failed",
        failed_stage=failed_stage,
        error_message=error_message,
    )


def resolve_local_path_string(raw_path: str) -> str:
    if not raw_path.strip():
        return ""
    return str(Path(raw_path).expanduser().resolve())


def resolve_batch_job_spec(
    *,
    mode: str,
    video: str,
    reference: str,
    output_dir: str,
    book_name: str | None,
    chapter: str | None,
    glossary_file: str | None,
) -> BatchJobSpec:
    return BatchJobSpec(
        video=resolve_local_path_string(video),
        reference=reference if not reference or is_url_reference(reference) else resolve_local_path_string(reference),
        output_dir=resolve_local_path_string(output_dir),
        mode=mode,
        book_name=book_name,
        chapter=chapter,
        glossary_file=resolve_local_path_string(glossary_file or "") or None,
    )


def parse_manifest_jobs(manifest_path: Path) -> list[dict[str, Any]]:
    try:
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JobRunnerError(f"无法读取 manifest: {manifest_path} | {exc}") from exc
    except yaml.YAMLError as exc:
        raise JobRunnerError(f"manifest YAML/JSON 解析失败: {manifest_path} | {exc}") from exc

    if isinstance(payload, list):
        jobs = payload
    elif isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        jobs = payload["jobs"]
    else:
        raise JobRunnerError(f"manifest 结构无效: {manifest_path}，顶层必须是 jobs 列表或包含 jobs 的对象。")

    normalized_jobs: list[dict[str, Any]] = []
    for index, item in enumerate(jobs, start=1):
        if not isinstance(item, dict):
            raise JobRunnerError(f"manifest 第 {index} 条任务无效，必须是对象。")
        normalized_jobs.append(item)
    return normalized_jobs


def validate_manifest_job_entry(
    *,
    item: dict[str, Any],
    default_book_name: str | None,
    default_chapter: str | None,
    default_glossary_file: str | None,
) -> BatchJobSpec:
    allowed_fields = {"video", "reference", "output_dir", "book_name", "chapter", "glossary_file"}
    unknown_fields = sorted(set(item) - allowed_fields)
    if unknown_fields:
        raise JobRunnerError(f"包含非法字段: {', '.join(unknown_fields)}")

    missing_fields = [field_name for field_name in ("video", "reference", "output_dir") if not str(item.get(field_name, "")).strip()]
    if missing_fields:
        raise JobRunnerError(f"缺少必填字段: {', '.join(missing_fields)}")

    return resolve_batch_job_spec(
        mode="manifest",
        video=str(item["video"]),
        reference=str(item["reference"]),
        output_dir=str(item["output_dir"]),
        book_name=str(item["book_name"]).strip() if item.get("book_name") else default_book_name,
        chapter=str(item["chapter"]).strip() if item.get("chapter") else default_chapter,
        glossary_file=str(item["glossary_file"]).strip() if item.get("glossary_file") else default_glossary_file,
    )


def find_paired_reference(video_path: Path, reference_dir: Path) -> Path | None:
    matches = [reference_dir / f"{video_path.stem}{extension}" for extension in supported_reference_extensions()]
    existing_matches = [candidate for candidate in matches if candidate.exists()]
    if len(existing_matches) > 1:
        raise JobRunnerError(f"basename={video_path.stem} 匹配到多个 reference 文件。")
    if not existing_matches:
        return None
    return existing_matches[0]


def build_batch_target_path(spec: BatchJobSpec) -> Path:
    return Path(spec.output_dir) / build_final_output_filename(
        Path(spec.video),
        book_name=spec.book_name,
        chapter=spec.chapter,
    )


def collect_duplicate_target_failures(specs: list[BatchJobSpec]) -> tuple[list[BatchJobSpec], list[BatchJobRuntime]]:
    grouped_specs: dict[Path, list[BatchJobSpec]] = {}
    for spec in specs:
        grouped_specs.setdefault(build_batch_target_path(spec), []).append(spec)

    valid_specs: list[BatchJobSpec] = []
    failed_items: list[BatchJobRuntime] = []
    for target_path, grouped in grouped_specs.items():
        if len(grouped) == 1:
            valid_specs.append(grouped[0])
            continue
        for spec in grouped:
            failed_items.append(
                build_failed_batch_runtime(
                    spec=spec,
                    failed_stage="input-validation",
                    error_message=f"重复 target: {target_path}",
                )
            )
    return valid_specs, failed_items


def load_batch_job_specs(
    *,
    base_loaded_settings: LoadedSettings,
    manifest: str | None = None,
    videos_dir: str | None = None,
    reference_dir: str | None = None,
    shared_reference: str | None = None,
    output_dir: str | None = None,
    book_name: str | None = None,
    chapter: str | None = None,
    glossary_file: str | None = None,
) -> tuple[list[BatchJobSpec], list[BatchJobRuntime]]:
    input_mode_count = sum(
        [
            1 if manifest else 0,
            1 if videos_dir and reference_dir and output_dir else 0,
            1 if videos_dir and shared_reference and output_dir else 0,
        ]
    )
    if input_mode_count != 1:
        raise JobRunnerError("批量入口参数无效：必须且只能选择 manifest、目录配对、共享参考 三种输入模式之一。")

    specs: list[BatchJobSpec] = []
    failed_items: list[BatchJobRuntime] = []

    if manifest:
        manifest_path = Path(manifest).expanduser().resolve()
        for item in parse_manifest_jobs(manifest_path):
            try:
                spec = validate_manifest_job_entry(
                    item=item,
                    default_book_name=book_name,
                    default_chapter=chapter,
                    default_glossary_file=glossary_file,
                )
            except JobRunnerError as exc:
                failed_items.append(
                    build_failed_batch_runtime(
                        spec=resolve_batch_job_spec(
                            mode="manifest",
                            video=str(item.get("video", "")),
                            reference=str(item.get("reference", "")),
                            output_dir=str(item.get("output_dir", "")),
                            book_name=str(item.get("book_name", "")).strip() or book_name,
                            chapter=str(item.get("chapter", "")).strip() or chapter,
                            glossary_file=str(item.get("glossary_file", "")).strip() or glossary_file,
                        ),
                        failed_stage="input-validation",
                        error_message=str(exc),
                    )
                )
                continue
            specs.append(spec)
    else:
        videos_path = Path(videos_dir or "").expanduser().resolve()
        output_path = Path(output_dir or "").expanduser().resolve()
        if not videos_path.exists() or not videos_path.is_dir():
            raise JobRunnerError(f"videos_dir 不存在或不是目录: {videos_path}")

        reference_path = Path(reference_dir).expanduser().resolve() if reference_dir else None
        if reference_path and (not reference_path.exists() or not reference_path.is_dir()):
            raise JobRunnerError(f"reference_dir 不存在或不是目录: {reference_path}")

        allowed_video_extensions = supported_video_extensions(base_loaded_settings)
        for video_path in sorted(videos_path.iterdir()):
            if not video_path.is_file():
                continue
            if video_path.suffix.lower() not in allowed_video_extensions:
                failed_items.append(
                    build_failed_batch_runtime(
                        spec=resolve_batch_job_spec(
                            mode="paired-dir" if reference_dir else "shared-reference",
                            video=str(video_path),
                            reference=str(shared_reference or ""),
                            output_dir=str(output_path),
                            book_name=book_name,
                            chapter=chapter,
                            glossary_file=glossary_file,
                        ),
                        failed_stage="input-validation",
                        error_message=f"不支持的视频扩展名: {video_path.name}",
                    )
                )
                continue

            if reference_path is not None:
                try:
                    matched_reference = find_paired_reference(video_path, reference_path)
                except JobRunnerError as exc:
                    failed_items.append(
                        build_failed_batch_runtime(
                            spec=resolve_batch_job_spec(
                                mode="paired-dir",
                                video=str(video_path),
                                reference="",
                                output_dir=str(output_path),
                                book_name=book_name,
                                chapter=chapter,
                                glossary_file=glossary_file,
                            ),
                            failed_stage="input-validation",
                            error_message=str(exc),
                        )
                    )
                    continue
                if matched_reference is None:
                    failed_items.append(
                        build_failed_batch_runtime(
                            spec=resolve_batch_job_spec(
                                mode="paired-dir",
                                video=str(video_path),
                                reference="",
                                output_dir=str(output_path),
                                book_name=book_name,
                                chapter=chapter,
                                glossary_file=glossary_file,
                            ),
                            failed_stage="input-validation",
                            error_message=f"缺少匹配的 reference: {video_path.stem}",
                        )
                    )
                    continue

                specs.append(
                    resolve_batch_job_spec(
                        mode="paired-dir",
                        video=str(video_path),
                        reference=str(matched_reference),
                        output_dir=str(output_path),
                        book_name=book_name,
                        chapter=chapter,
                        glossary_file=glossary_file,
                    )
                )
                continue

            if not shared_reference:
                raise JobRunnerError("共享参考模式缺少 shared_reference。")
            specs.append(
                resolve_batch_job_spec(
                    mode="shared-reference",
                    video=str(video_path),
                    reference=shared_reference,
                    output_dir=str(output_path),
                    book_name=book_name,
                    chapter=chapter,
                    glossary_file=glossary_file,
                )
            )

    valid_specs, duplicate_target_failures = collect_duplicate_target_failures(specs)
    failed_items.extend(duplicate_target_failures)
    return valid_specs, failed_items


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


def is_network_unreachable_error(exc: OSError) -> bool:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        error_no = getattr(current, "errno", None)
        if error_no in {101, 65}:
            return True
        if "network is unreachable" in str(current).lower():
            return True
        reason = getattr(current, "reason", None)
        current = reason if isinstance(reason, BaseException) else None
    return False


@contextmanager
def force_ipv4_resolution():
    original_getaddrinfo = socket.getaddrinfo

    def ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        resolved = original_getaddrinfo(host, port, family, type, proto, flags)
        ipv4_only = [item for item in resolved if item[0] == socket.AF_INET]
        return ipv4_only or resolved

    socket.getaddrinfo = ipv4_only_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def read_url_payload(
    request: Request,
    *,
    prefer_ipv4: bool = False,
) -> tuple[str, str, bytes]:
    if prefer_ipv4:
        with force_ipv4_resolution():
            with urlopen(request, timeout=WEB_REQUEST_TIMEOUT_SECONDS) as response:
                return (
                    response.headers.get_content_type(),
                    response.headers.get_content_charset() or "utf-8",
                    response.read(),
                )

    with urlopen(request, timeout=WEB_REQUEST_TIMEOUT_SECONDS) as response:
        return (
            response.headers.get_content_type(),
            response.headers.get_content_charset() or "utf-8",
            response.read(),
        )


def fetch_reference_from_url(reference_url: str, destination_dir: Path, basename: str) -> tuple[Path, str]:
    request = Request(reference_url, headers={"User-Agent": "transcript-pipeline/0.1"})
    try:
        content_type, charset, payload = read_url_payload(request)
    except OSError as exc:
        if is_network_unreachable_error(exc):
            try:
                content_type, charset, payload = read_url_payload(request, prefer_ipv4=True)
            except OSError as retry_exc:
                raise JobRunnerError(f"网页参考抓取失败: {reference_url} | {retry_exc}") from retry_exc
        else:
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


def prepare_batch_jobs(
    *,
    project_root: Path,
    base_loaded_settings: LoadedSettings,
    job_specs: list[BatchJobSpec],
) -> list[BatchJobRuntime]:
    runtimes: list[BatchJobRuntime] = []
    profile_name = base_loaded_settings.active_profile_name

    for spec in job_specs:
        job_id = create_job_id()
        job_paths = build_job_paths(project_root, job_id)
        try:
            prepared_inputs = prepare_job_inputs(
                video_source=Path(spec.video),
                reference_source=spec.reference,
                job_paths=job_paths,
            )
            write_job_settings(
                project_root=project_root,
                loaded_settings=base_loaded_settings,
                job_paths=job_paths,
                profile_name=profile_name,
                glossary_file=spec.glossary_file,
                book_name=spec.book_name,
                chapter=spec.chapter,
            )
            write_job_manifest(
                loaded_settings=base_loaded_settings,
                job_paths=job_paths,
                prepared_inputs=prepared_inputs,
                video_source=Path(spec.video),
                reference_source=spec.reference,
                output_dir=Path(spec.output_dir),
                profile_name=profile_name,
                book_name=spec.book_name,
                chapter=spec.chapter,
                glossary_file=spec.glossary_file,
            )
        except JobRunnerError as exc:
            runtimes.append(
                build_failed_batch_runtime(
                    spec=spec,
                    job_id=job_id,
                    job_root=job_paths.job_root,
                    failed_stage="prepare-job",
                    error_message=str(exc),
                )
            )
            continue

        runtimes.append(
            BatchJobRuntime(
                job_id=job_id,
                job_root=job_paths.job_root,
                spec=spec,
                status="pending",
            )
        )

    return runtimes


def execute_batch_stage_for_runtime(
    *,
    stage_name: str,
    runtime: BatchJobRuntime,
    project_root: Path,
    logger: logging.Logger,
    backend_override: str | None = None,
) -> None:
    if runtime.status == "failed":
        return

    try:
        job_loaded_settings = load_settings(
            settings_path=runtime.job_root / "settings.generated.yaml",
            project_root=project_root,
        )
        current_backend_override = backend_override if stage_name == "refine" else None
        exit_code = run_stage(stage_name, job_loaded_settings, logger, backend_override=current_backend_override)
        if exit_code != 0:
            raise JobRunnerError(f"job 主链失败: stage={stage_name} exit_code={exit_code}")

        if stage_name == "export-markdown":
            job_paths = build_job_paths(project_root, runtime.job_id)
            _, copied_output_path = copy_final_output(
                job_paths,
                Path(runtime.spec.output_dir),
                build_final_output_filename(
                    Path(runtime.spec.video),
                    book_name=runtime.spec.book_name,
                    chapter=runtime.spec.chapter,
                ),
            )
            runtime.copied_output_path = copied_output_path
            runtime.status = "success"
    except (ConfigLoadError, JobRunnerError) as exc:
        runtime.status = "failed"
        runtime.failed_stage = stage_name
        runtime.error_message = str(exc)


def run_jobs_with_limited_concurrency(
    *,
    stage_name: str,
    runtimes: list[BatchJobRuntime],
    project_root: Path,
    logger: logging.Logger,
    remote_concurrency: int,
    backend_override: str | None = None,
) -> None:
    if not runtimes:
        return

    max_workers = max(1, remote_concurrency)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                execute_batch_stage_for_runtime,
                stage_name=stage_name,
                runtime=runtime,
                project_root=project_root,
                logger=logger,
                backend_override=backend_override,
            )
            for runtime in runtimes
        ]
        for future in as_completed(futures):
            future.result()


def execute_remote_pipeline_for_runtime(
    *,
    runtime: BatchJobRuntime,
    project_root: Path,
    logger: logging.Logger,
    backend_override: str | None = None,
) -> None:
    for stage_name in ("prepare-reference", "refine", "export-markdown"):
        execute_batch_stage_for_runtime(
            stage_name=stage_name,
            runtime=runtime,
            project_root=project_root,
            logger=logger,
            backend_override=backend_override,
        )
        if runtime.status == "failed":
            return


def run_batch_stage(
    *,
    stage_name: str,
    runtimes: list[BatchJobRuntime],
    project_root: Path,
    logger: logging.Logger,
    remote_concurrency: int,
    backend_override: str | None = None,
) -> None:
    active_runtimes = [runtime for runtime in runtimes if runtime.status != "failed"]
    if not active_runtimes:
        return

    if stage_name in {"prepare-reference", "refine"}:
        run_jobs_with_limited_concurrency(
            stage_name=stage_name,
            runtimes=active_runtimes,
            project_root=project_root,
            logger=logger,
            remote_concurrency=remote_concurrency,
            backend_override=backend_override,
        )
        return

    for runtime in active_runtimes:
        execute_batch_stage_for_runtime(
            stage_name=stage_name,
            runtime=runtime,
            project_root=project_root,
            logger=logger,
            backend_override=backend_override,
        )


def serialize_batch_runtime(runtime: BatchJobRuntime) -> dict[str, Any]:
    return {
        "job_id": runtime.job_id,
        "mode": runtime.spec.mode,
        "video_source": runtime.spec.video,
        "reference_source": runtime.spec.reference,
        "output_dir": runtime.spec.output_dir,
        "book_name": runtime.spec.book_name or "",
        "chapter": runtime.spec.chapter or "",
        "glossary_file": runtime.spec.glossary_file or "",
        "status": runtime.status,
        "failed_stage": runtime.failed_stage or "",
        "error_message": runtime.error_message or "",
        "copied_output_path": str(runtime.copied_output_path) if runtime.copied_output_path else "",
    }


def write_batch_summary(
    *,
    project_root: Path,
    summary: BatchRunSummary,
) -> None:
    batch_root = build_batch_root(project_root, summary.batch_id)
    manifest_payload = {
        "batch_id": summary.batch_id,
        "total": summary.total,
        "items": [
            {
                "job_id": item.job_id,
                "mode": item.spec.mode,
                "video_source": item.spec.video,
                "reference_source": item.spec.reference,
                "output_dir": item.spec.output_dir,
                "book_name": item.spec.book_name or "",
                "chapter": item.spec.chapter or "",
                "glossary_file": item.spec.glossary_file or "",
            }
            for item in summary.items
        ],
    }
    (batch_root / "manifest.json").write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_payload = {
        "batch_id": summary.batch_id,
        "total": summary.total,
        "success": summary.success,
        "failed": summary.failed,
        "items": [serialize_batch_runtime(item) for item in summary.items],
    }
    (batch_root / "summary.json").write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Batch Summary: {summary.batch_id}",
        "",
        f"- total: {summary.total}",
        f"- success: {summary.success}",
        f"- failed: {summary.failed}",
        "",
    ]
    for item in summary.items:
        lines.append(f"## {item.job_id or 'invalid'}")
        lines.append(f"- status: {item.status}")
        lines.append(f"- mode: {item.spec.mode}")
        lines.append(f"- video: {item.spec.video}")
        lines.append(f"- reference: {item.spec.reference}")
        lines.append(f"- failed_stage: {item.failed_stage or ''}")
        lines.append(f"- copied_output_path: {item.copied_output_path or ''}")
        lines.append(f"- error_message: {item.error_message or ''}")
        lines.append("")
    (batch_root / "summary.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_batch_jobs(
    *,
    project_root: Path,
    base_loaded_settings: LoadedSettings,
    job_specs: list[BatchJobSpec],
    failed_runtimes: list[BatchJobRuntime] | None = None,
    remote_concurrency: int = 2,
    batch_id: str | None = None,
    backend_override: str | None = None,
) -> BatchRunSummary:
    current_batch_id = batch_id or create_batch_id()
    logger = setup_logging(base_loaded_settings.settings.runtime.log_level)
    runtimes = list(failed_runtimes or [])
    runtimes.extend(
        prepare_batch_jobs(
            project_root=project_root,
            base_loaded_settings=base_loaded_settings,
            job_specs=job_specs,
        )
    )

    active_runtimes = [runtime for runtime in runtimes if runtime.status != "failed"]
    max_workers = max(1, remote_concurrency)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        remote_futures = []
        for runtime in active_runtimes:
            for stage_name in ("extract-audio", "transcribe"):
                execute_batch_stage_for_runtime(
                    stage_name=stage_name,
                    runtime=runtime,
                    project_root=project_root,
                    logger=logger,
                    backend_override=backend_override,
                )
                if runtime.status == "failed":
                    break

            if runtime.status == "failed":
                continue

            remote_futures.append(
                executor.submit(
                    execute_remote_pipeline_for_runtime,
                    runtime=runtime,
                    project_root=project_root,
                    logger=logger,
                    backend_override=backend_override,
                )
            )

        for future in as_completed(remote_futures):
            future.result()

    success_count = sum(1 for item in runtimes if item.status == "success")
    failed_count = sum(1 for item in runtimes if item.status == "failed")
    summary = BatchRunSummary(
        batch_id=current_batch_id,
        total=len(runtimes),
        success=success_count,
        failed=failed_count,
        items=runtimes,
    )
    write_batch_summary(project_root=project_root, summary=summary)
    return summary


def get_batch_exit_code(summary: BatchRunSummary) -> int:
    if summary.success == summary.total and summary.total > 0:
        return 0
    if summary.success > 0:
        return 2
    return 1


def run_job_pipeline(
    loaded_settings: LoadedSettings,
    logger: logging.Logger,
    backend_override: str | None = None,
) -> None:
    raw_stages = loaded_settings.settings.pipeline.stages if loaded_settings.settings.pipeline else []
    if not raw_stages:
        raise JobRunnerError("当前配置未定义主链阶段列表。")

    stages = [normalize_stage_name(stage_name) for stage_name in raw_stages]
    logger.info("job 主链启动 | profile=%s | stages=%s", loaded_settings.active_profile_name, ",".join(stages))
    for stage_name in stages:
        logger.info("job 主链执行 | stage=%s", stage_name)
        current_backend_override = backend_override if stage_name == "refine" else None
        exit_code = run_stage(stage_name, loaded_settings, logger, backend_override=current_backend_override)
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
    backend: str | None = None,
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
    run_job_pipeline(job_loaded_settings, logger, backend_override=backend)

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
