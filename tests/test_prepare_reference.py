from __future__ import annotations

from pathlib import Path

import pytest

from src.config_loader import load_settings
from src.reference_utils import (
    GeminiOCRError,
    ReferenceInputEmptyError,
    build_reference_output_paths,
    is_effectively_empty_text,
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


def test_is_effectively_empty_text_uses_content_length_threshold() -> None:
    assert is_effectively_empty_text("")
    assert is_effectively_empty_text(" \n ")
    assert not is_effectively_empty_text("这是足够长的可提取文字内容")


def test_prepare_reference_file_uses_ocr_fallback_when_pdf_text_layer_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("", ["PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。"]),
    )
    monkeypatch.setattr(
        "src.reference_utils.run_gemini_pdf_ocr",
        lambda _path, _settings: ("这是 Gemini OCR 提取出来的中文文本内容。", ["PDF 文字层为空，已使用 Gemini OCR fallback。model=gemini-3-flash-preview"]),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "gemini_cli_pdf_ocr"
    assert "Gemini OCR fallback" in " ".join(result.warnings)
    assert "Gemini OCR 提取出来的中文文本内容" in result.extracted_text


def test_prepare_reference_file_prefers_gemini_ocr_even_when_pdf_has_text_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "book.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.run_gemini_pdf_ocr",
        lambda _path, _settings: ("这是 Gemini 优先 OCR 的结果。", ["已优先使用 Gemini OCR。model=gemini-3-flash-preview"]),
    )
    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("这是 PDF 文字层内容。", []),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "gemini_cli_pdf_ocr"
    assert "Gemini 优先 OCR 的结果" in result.extracted_text
    assert "优先使用 Gemini OCR" in " ".join(result.warnings)


def test_prepare_reference_file_falls_back_to_text_layer_when_gemini_ocr_fails_and_pdf_has_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "book.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    def fake_gemini_ocr(_path: Path, _settings) -> tuple[str, list[str]]:
        raise GeminiOCRError("capacity exhausted")

    monkeypatch.setattr("src.reference_utils.run_gemini_pdf_ocr", fake_gemini_ocr)
    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("这是 PDF 文字层内容。", []),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "pypdf_text_extract"
    assert "Gemini OCR 失败，已回退到 PDF 文字层提取" in " ".join(result.warnings)
    assert result.extracted_text == "这是 PDF 文字层内容。"


def test_prepare_reference_file_falls_back_to_ocrmypdf_when_gemini_ocr_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("", ["PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。"]),
    )

    def fake_gemini_ocr(_path: Path, _settings) -> tuple[str, list[str]]:
        raise GeminiOCRError("network close")

    monkeypatch.setattr("src.reference_utils.run_gemini_pdf_ocr", fake_gemini_ocr)
    monkeypatch.setattr(
        "src.reference_utils.run_tesseract_pdf_ocr",
        lambda _path, _settings: ("这是 ocrmypdf OCR 提取出来的中文文本内容。", ["PDF 文字层为空，已使用 OCR fallback。backend=ocrmypdf_tesseract"]),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "ocrmypdf_tesseract"
    assert "Gemini OCR 失败，已回退到 ocrmypdf" in " ".join(result.warnings)
    assert "ocrmypdf OCR 提取出来的中文文本内容" in result.extracted_text


def test_prepare_reference_file_keeps_pdf_failure_when_ocr_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": False})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("", ["PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。"]),
    )
    monkeypatch.setattr(
        "src.reference_utils.run_gemini_pdf_ocr",
        lambda _path, _settings: (_ for _ in ()).throw(GeminiOCRError("disabled in test")),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is False
    assert result.extraction_method == "pypdf_text_extract"
    assert result.warnings == [
        "Gemini OCR 失败，且当前未启用 OCR fallback。reason=disabled in test",
        "PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。",
    ]
