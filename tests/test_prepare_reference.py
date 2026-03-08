from __future__ import annotations

from pathlib import Path

import pytest

from src.config_loader import load_settings
from src.reference_utils import (
    ReferenceInputEmptyError,
    build_reference_output_paths,
    iter_reference_files,
    prepare_reference_file,
    read_text_file,
)
from tests.helpers import write_minimal_settings


def test_prepare_reference_batch_raises_when_reference_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    (tmp_path / "data/input/reference").mkdir(parents=True, exist_ok=True)

    loaded_settings = load_settings(project_root=tmp_path)

    from src.reference_utils import prepare_reference_batch

    with pytest.raises(ReferenceInputEmptyError):
        prepare_reference_batch(loaded_settings)


def test_read_text_file_for_txt(tmp_path: Path) -> None:
    source = tmp_path / "chapter01.txt"
    source.write_text("第一段\n第二段", encoding="utf-8")

    assert read_text_file(source) == "第一段\n第二段"


def test_read_markdown_file_via_prepare_reference_file(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "outline.md"
    source.write_text("# 标题\n\n正文", encoding="utf-8")

    loaded_settings = load_settings(project_root=tmp_path)
    result = prepare_reference_file(source, loaded_settings)

    assert result.source_type == "md"
    assert result.success is True
    assert "# 标题" in result.extracted_text


def test_iter_reference_files_filters_supported_extensions(tmp_path: Path) -> None:
    (tmp_path / "book.txt").write_text("txt", encoding="utf-8")
    (tmp_path / "notes.MD").write_text("md", encoding="utf-8")
    (tmp_path / "scan.pdf").write_text("pdf", encoding="utf-8")
    (tmp_path / "image.png").write_text("png", encoding="utf-8")

    files = iter_reference_files(tmp_path, [".txt", ".md", ".pdf"])

    assert [path.name for path in files] == ["book.txt", "notes.MD", "scan.pdf"]


def test_build_reference_output_paths_uses_reference_basename(tmp_path: Path) -> None:
    reference_path = tmp_path / "chapter-03.pdf"
    output_dir = tmp_path / "data/intermediate/extracted_text"

    output_paths = build_reference_output_paths(reference_path, output_dir)

    assert output_paths.txt_path == output_dir / "chapter-03.txt"
    assert output_paths.json_path == output_dir / "chapter-03.json"
