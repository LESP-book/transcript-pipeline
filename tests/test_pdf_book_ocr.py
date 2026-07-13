from __future__ import annotations

from pathlib import Path

import pytest

from src.pdf_book_ocr import (
    PDFBookOCRError,
    build_pdf_book_output_path,
    iter_pdf_book_files,
    ocr_pdf_book_batch,
    summarize_pdf_book_ocr,
)
from src.reference_utils import CodexOCRError


def test_iter_pdf_book_files_recursively_sorts_and_ignores_non_pdf(tmp_path: Path) -> None:
    (tmp_path / "第二册").mkdir()
    (tmp_path / "第一册").mkdir()
    (tmp_path / "第二册" / "chapter.pdf").write_bytes(b"pdf")
    (tmp_path / "第一册" / "chapter.PDF").write_bytes(b"pdf")
    (tmp_path / "第一册" / "notes.txt").write_text("notes", encoding="utf-8")

    files = iter_pdf_book_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "第一册/chapter.PDF",
        "第二册/chapter.pdf",
    ]


def test_iter_pdf_book_files_rejects_non_pdf_file(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(PDFBookOCRError, match="不是 PDF"):
        iter_pdf_book_files(source)


def test_build_pdf_book_output_path_preserves_batch_directory_structure(tmp_path: Path) -> None:
    input_dir = tmp_path / "books"
    source = input_dir / "part-01" / "chapter.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf")
    output_dir = tmp_path / "ocr-output"

    output_path = build_pdf_book_output_path(input_dir, source, output_dir)

    assert output_path == output_dir.resolve() / "part-01" / "chapter.txt"


def test_ocr_pdf_book_batch_uses_explicit_output_paths_and_continues_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "books"
    good_source = input_dir / "part-01" / "good.pdf"
    bad_source = input_dir / "part-02" / "bad.pdf"
    good_source.parent.mkdir(parents=True)
    bad_source.parent.mkdir(parents=True)
    good_source.write_bytes(b"pdf")
    bad_source.write_bytes(b"pdf")
    output_dir = tmp_path / "ocr-output"
    seen_sidecar_paths: list[Path] = []

    def fake_run_codex_api_pdf_ocr(
        source_pdf: Path,
        _loaded_settings: object,
        *,
        sidecar_path: Path | None = None,
    ) -> tuple[str, list[str]]:
        assert sidecar_path is not None
        seen_sidecar_paths.append(sidecar_path)
        if source_pdf.name == "bad.pdf":
            raise CodexOCRError("远程服务不可用")
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text("识别后的书籍内容", encoding="utf-8")
        return "识别后的书籍内容", ["已完成"]

    monkeypatch.setattr("src.pdf_book_ocr.run_codex_api_pdf_ocr", fake_run_codex_api_pdf_ocr)

    summary = ocr_pdf_book_batch(input_dir, output_dir, object())

    assert summary.success_count == 1
    assert summary.failure_count == 1
    assert summarize_pdf_book_ocr(summary) == "total=2, success=1, failed=1"
    assert seen_sidecar_paths == [
        output_dir.resolve() / "part-01" / "good.txt",
        output_dir.resolve() / "part-02" / "bad.txt",
    ]
    assert (output_dir / "part-01" / "good.txt").read_text(encoding="utf-8") == "识别后的书籍内容"
    assert not (output_dir / "part-02" / "bad.txt").exists()
