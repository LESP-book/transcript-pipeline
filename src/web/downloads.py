from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from src.markdown_utils import markdown_document_to_plain_text


ResultDownloadFormat = str


@dataclass(frozen=True)
class ResultDownload:
    path: Path | None
    content: bytes | None
    filename: str
    media_type: str


def normalize_result_format(raw_format: str | None) -> ResultDownloadFormat:
    format_name = str(raw_format or "markdown").strip().lower()
    if format_name in {"markdown", "md"}:
        return "markdown"
    if format_name == "txt":
        return "txt"
    raise ValueError("不支持的结果格式，请使用 markdown 或 txt。")


def _result_media_type(result_format: ResultDownloadFormat) -> str:
    if result_format == "txt":
        return "text/plain; charset=utf-8"
    return "text/markdown; charset=utf-8"


def _resolved_file(raw_path: object) -> Path | None:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return None
    return Path(path_text).expanduser().resolve()


def _require_existing_file(path: Path | None, *, missing_detail: str) -> Path:
    if path is None or not path.is_file():
        raise FileNotFoundError(missing_detail)
    return path


def _first_existing_file(*paths: Path | None) -> Path | None:
    for path in paths:
        if path is not None and path.is_file():
            return path
    return None


def _text_result_path(markdown_path: Path) -> Path:
    return markdown_path.with_suffix(".txt")


def build_result_download(markdown_path: Path, result_format: ResultDownloadFormat) -> ResultDownload:
    if result_format == "markdown":
        return ResultDownload(
            path=markdown_path,
            content=None,
            filename=markdown_path.name,
            media_type=_result_media_type(result_format),
        )

    text_path = _text_result_path(markdown_path)
    if text_path.is_file():
        return ResultDownload(
            path=text_path,
            content=None,
            filename=text_path.name,
            media_type=_result_media_type(result_format),
        )

    markdown_text = markdown_path.read_text(encoding="utf-8")
    text_content = markdown_document_to_plain_text(markdown_text).encode("utf-8")
    return ResultDownload(
        path=None,
        content=text_content,
        filename=text_path.name,
        media_type=_result_media_type(result_format),
    )


def resolve_job_result_path(project_root: Path, state: dict[str, Any]) -> Path:
    if state.get("status") != "success":
        raise ValueError("任务尚未成功完成，暂无可下载结果。")

    job_id = str(state.get("id") or "").strip()
    output_path = _resolved_file(state.get("output_path"))
    fallback_path = project_root / "data/jobs" / job_id / "output/final/source.md"
    return _require_existing_file(
        _first_existing_file(output_path, fallback_path),
        missing_detail="任务结果文件不存在。",
    )


def resolve_batch_item_result_path(project_root: Path, state: dict[str, Any], item_job_id: str) -> Path:
    for raw_item in state.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        if str(raw_item.get("job_id") or "") != item_job_id:
            continue
        if raw_item.get("status") != "success":
            raise ValueError("该子任务尚未成功完成，暂无可下载结果。")
        fallback_path = project_root / "data/jobs" / item_job_id / "output/final/source.md"
        return _require_existing_file(
            _first_existing_file(_resolved_file(raw_item.get("copied_output_path")), fallback_path),
            missing_detail="子任务结果文件不存在。",
        )
    raise FileNotFoundError(f"批量子任务不存在: {item_job_id}")


def _write_result_to_archive(archive: ZipFile, archive_name: str, markdown_path: Path, result_format: ResultDownloadFormat) -> None:
    download = build_result_download(markdown_path, result_format)
    if download.path is not None:
        archive.write(download.path, archive_name)
        return
    if download.content is None:
        raise FileNotFoundError(f"任务结果文件不存在: {markdown_path}")
    archive.writestr(archive_name, download.content)


def build_batch_result_archive(
    project_root: Path,
    batch_id: str,
    state: dict[str, Any],
    result_format: ResultDownloadFormat = "markdown",
) -> bytes:
    batch_root = project_root / "data/jobs/batches" / batch_id
    buffer = BytesIO()
    file_count = 0
    normalized_format = normalize_result_format(result_format)

    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for summary_name in ("summary.md", "summary.json", "manifest.json"):
            summary_path = batch_root / summary_name
            if summary_path.is_file():
                archive.write(summary_path, summary_name)
                file_count += 1

        for index, raw_item in enumerate(state.get("items") or [], start=1):
            if not isinstance(raw_item, dict) or raw_item.get("status") != "success":
                continue
            job_id = str(raw_item.get("job_id") or f"item-{index}").replace("/", "_")
            result_path = _first_existing_file(
                _resolved_file(raw_item.get("copied_output_path")),
                project_root / "data/jobs" / job_id / "output/final/source.md",
            )
            if result_path is None:
                continue
            archive_filename = result_path.name if normalized_format == "markdown" else _text_result_path(result_path).name
            archive_name = f"results/{index:03d}-{job_id}-{archive_filename}"
            _write_result_to_archive(archive, archive_name, result_path, normalized_format)
            file_count += 1

    if file_count == 0:
        raise FileNotFoundError("批量任务暂无可下载结果。")

    buffer.seek(0)
    return buffer.read()
