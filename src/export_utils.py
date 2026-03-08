from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.runtime_utils import ensure_directory
from src.schemas import LoadedSettings


class ExportError(RuntimeError):
    """Raised when stage 7 export fails."""


class ExportInputEmptyError(ExportError):
    """Raised when there are no refined files to export."""


@dataclass(frozen=True)
class ExportInputPaths:
    refined_json_path: Path


@dataclass(frozen=True)
class ExportOutputPath:
    markdown_path: Path


@dataclass(frozen=True)
class ExportBatchItem:
    basename: str
    output_path: Path | None
    success: bool
    skipped: bool
    reason: str | None = None


@dataclass(frozen=True)
class ExportBatchSummary:
    total: int
    success: int
    skipped: int
    failed: int
    items: list[ExportBatchItem]


def iter_refined_json_files(refined_dir: Path) -> list[Path]:
    if not refined_dir.exists():
        return []
    return sorted(path for path in refined_dir.iterdir() if path.is_file() and path.suffix.lower() == ".json")


def build_markdown_output_path(refined_json_path: Path, output_dir: Path) -> ExportOutputPath:
    return ExportOutputPath(markdown_path=output_dir / f"{refined_json_path.stem}.md")


def load_json_payload(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExportError(f"无法读取{label}文件: {path.name} | {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ExportError(f"{label} JSON 解析失败: {path.name} | {exc}") from exc

    if not isinstance(payload, dict):
        raise ExportError(f"{label} JSON 结构无效: {path.name}")
    return payload


def load_refined_payload(refined_json_path: Path) -> dict[str, Any]:
    payload = load_json_payload(refined_json_path, "refined")
    final_markdown = str(payload.get("final_markdown", "")).strip()
    if not final_markdown:
        raise ExportError(f"refined JSON 缺少 final_markdown: {refined_json_path.name}")
    return payload


def resolve_export_input_paths(
    refined_json_path: Path,
    refined_payload: dict[str, Any],
    loaded_settings: LoadedSettings,
) -> ExportInputPaths:
    return ExportInputPaths(
        refined_json_path=refined_json_path,
    )


def render_markdown_document(
    *,
    refined_payload: dict[str, Any],
    refined_json_path: Path,
) -> str:
    _ = refined_json_path
    return str(refined_payload.get("final_markdown", "")).strip() + "\n"


def write_markdown_result(output_path: ExportOutputPath, markdown_text: str) -> None:
    ensure_directory(output_path.markdown_path.parent)
    try:
        output_path.markdown_path.write_text(markdown_text, encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"无法写入 Markdown 输出: {output_path.markdown_path} | {exc}") from exc


def export_markdown_batch(
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> ExportBatchSummary:
    refined_dir = loaded_settings.path_for("refined_dir")
    output_dir = ensure_directory(loaded_settings.path_for("final_dir"))
    refined_files = iter_refined_json_files(refined_dir)

    if not refined_files:
        raise ExportInputEmptyError(f"refined 输入目录中没有可处理的 JSON 文件: {refined_dir}")

    items: list[ExportBatchItem] = []
    success_count = 0
    for refined_json_path in refined_files:
        refined_payload = load_refined_payload(refined_json_path)
        resolve_export_input_paths(refined_json_path, refined_payload, loaded_settings)
        output_path = build_markdown_output_path(refined_json_path, output_dir)
        markdown_text = render_markdown_document(
            refined_payload=refined_payload,
            refined_json_path=refined_json_path,
        )
        write_markdown_result(output_path, markdown_text)
        items.append(
            ExportBatchItem(
                basename=refined_json_path.stem,
                output_path=output_path.markdown_path,
                success=True,
                skipped=False,
            )
        )
        success_count += 1
        if logger:
            paragraph_count = len([item for item in str(refined_payload.get("final_markdown", "")).split("\n\n") if item.strip()])
            logger.info(
                "Markdown 导出完成 | %s | paragraphs=%s",
                refined_json_path.stem,
                paragraph_count,
            )

    return ExportBatchSummary(
        total=len(refined_files),
        success=success_count,
        skipped=0,
        failed=0,
        items=items,
    )


def summarize_export_results(summary: ExportBatchSummary) -> str:
    return (
        f"total={summary.total}, success={summary.success}, skipped={summary.skipped}, "
        f"failed={summary.failed}"
    )
