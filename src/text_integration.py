from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.runtime_utils import ensure_directory


class TextIntegrationError(RuntimeError):
    """OCR 文本片段整合失败。"""


@dataclass(frozen=True)
class TextIntegrationResult:
    """一次文本整合的可追踪结果。"""

    output_path: Path
    source_paths: tuple[Path, ...]
    character_count: int


def _natural_sort_key(path: Path, root: Path) -> tuple[tuple[int, object], ...]:
    relative_name = path.relative_to(root).as_posix().casefold()
    parts = re.split(r"(\d+)", relative_name)
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
        if part
    )


def iter_ocr_text_paths(input_path: Path, *, excluded_paths: set[Path] | None = None) -> list[Path]:
    """返回单个 TXT 或目录中的 TXT，并按自然顺序排列。"""
    resolved_input = input_path.expanduser().resolve()
    excluded = {path.expanduser().resolve() for path in (excluded_paths or set())}

    if resolved_input.is_file():
        if resolved_input.suffix.lower() != ".txt":
            raise TextIntegrationError(f"输入文件不是 TXT: {resolved_input}")
        if resolved_input in excluded:
            raise TextIntegrationError(f"输入 TXT 与输出路径相同，拒绝覆盖源文件: {resolved_input}")
        return [resolved_input]

    if not resolved_input.is_dir():
        raise TextIntegrationError(f"输入路径不存在或不是文件夹: {resolved_input}")

    text_paths = [
        path.resolve()
        for path in resolved_input.rglob("*")
        if path.is_file()
        and path.suffix.lower() == ".txt"
        and path.resolve() not in excluded
    ]
    if not text_paths:
        raise TextIntegrationError(f"输入文件夹中没有找到 TXT 片段: {resolved_input}")
    return sorted(text_paths, key=lambda path: _natural_sort_key(path, resolved_input))


def _read_and_normalize_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise TextIntegrationError(f"无法读取 OCR TXT: {path} | {exc}") from exc
    except UnicodeDecodeError as exc:
        raise TextIntegrationError(f"OCR TXT 不是有效的 UTF-8 文本: {path} | {exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def build_default_integrated_output_path(input_path: Path) -> Path:
    """构造不覆盖输入的默认整合 TXT 路径。"""
    resolved_input = input_path.expanduser().resolve()
    if resolved_input.is_file():
        return resolved_input.with_name(f"{resolved_input.stem}.integrated.txt")
    return resolved_input.parent / f"{resolved_input.name}.integrated.txt"


def integrate_ocr_texts(input_path: Path, output_path: Path) -> TextIntegrationResult:
    """按稳定顺序整合 OCR TXT，片段之间保留一个明确换行。"""
    resolved_output = output_path.expanduser().resolve()
    if resolved_output.exists() and resolved_output.is_dir():
        raise TextIntegrationError(f"输出路径是文件夹，不是 TXT 文件: {resolved_output}")

    source_paths = iter_ocr_text_paths(input_path, excluded_paths={resolved_output})
    parts = [_read_and_normalize_text(path).rstrip("\n") for path in source_paths]
    integrated_text = "\n".join(parts)

    try:
        ensure_directory(resolved_output.parent)
        resolved_output.write_text(integrated_text, encoding="utf-8")
    except OSError as exc:
        raise TextIntegrationError(f"无法写入整合 TXT: {resolved_output} | {exc}") from exc

    return TextIntegrationResult(
        output_path=resolved_output,
        source_paths=tuple(source_paths),
        character_count=len(integrated_text),
    )
