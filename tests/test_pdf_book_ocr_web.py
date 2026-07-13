from __future__ import annotations

from pathlib import Path

import pytest

from src.pdf_book_ocr import PDFBookOCRItem, PDFBookOCRSummary
from src.web.pdf_book_ocr import (
    PDFBookOCRTaskError,
    build_pdf_book_ocr_task_paths,
    create_pdf_book_ocr_task_id,
    resolve_pdf_book_ocr_output_file,
    resolve_uploaded_pdf_ocr_input,
)
from src.web.state_store import create_initial_state, read_json_file, write_json_file
from tests.helpers import write_minimal_settings


def test_resolve_uploaded_pdf_ocr_input_rejects_path_outside_pdf_ocr_upload_root(tmp_path: Path) -> None:
    source = tmp_path / "outside.pdf"
    source.write_bytes(b"pdf")

    with pytest.raises(PDFBookOCRTaskError, match="本页面上传"):
        resolve_uploaded_pdf_ocr_input(tmp_path, str(source))


def test_resolve_pdf_book_ocr_output_file_rejects_path_traversal(tmp_path: Path) -> None:
    task_paths = build_pdf_book_ocr_task_paths(tmp_path, create_pdf_book_ocr_task_id())

    with pytest.raises(PDFBookOCRTaskError, match="超出"):
        resolve_pdf_book_ocr_output_file(task_paths, "../state.txt")


def test_execute_pdf_book_ocr_writes_isolated_task_state_and_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api_server import create_app
    from src.web.tasks import execute_pdf_book_ocr

    write_minimal_settings(tmp_path)
    input_path = tmp_path / "data/uploads/pdf-ocr/20260713/group-001/哲学史.pdf"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(b"%PDF-1.4 fake")

    app = create_app(project_root=tmp_path)
    task_id = create_pdf_book_ocr_task_id()
    task_paths = build_pdf_book_ocr_task_paths(tmp_path, task_id)
    write_json_file(task_paths.state_path, create_initial_state(task_id, "pdf-ocr"))

    def fake_ocr_pdf_book_batch(source: Path, output_dir: Path, _loaded_settings) -> PDFBookOCRSummary:
        assert source == input_path.resolve()
        output_path = output_dir / "哲学史.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("OCR 识别结果", encoding="utf-8")
        return PDFBookOCRSummary(
            items=[
                PDFBookOCRItem(
                    source_pdf=source,
                    output_text_path=output_path,
                    success=True,
                    text_length=len("OCR 识别结果"),
                    warnings=["已完成"],
                )
            ]
        )

    monkeypatch.setattr("src.web.tasks.ocr_pdf_book_batch", fake_ocr_pdf_book_batch)

    execute_pdf_book_ocr(
        app=app,
        task_id=task_id,
        payload={"input_path": str(input_path)},
    )

    state = read_json_file(task_paths.state_path)
    assert state["status"] == "success"
    assert state["current_stage"] == "done"
    assert state["total"] == 1
    assert state["success"] == 1
    assert state["failed"] == 0
    assert state["items"] == [
        {
            "source_file": "哲学史.pdf",
            "output_file": "哲学史.txt",
            "success": True,
            "text_length": len("OCR 识别结果"),
            "warnings": ["已完成"],
            "error": "",
        }
    ]
    assert (task_paths.output_dir / "哲学史.txt").read_text(encoding="utf-8") == "OCR 识别结果"


def test_execute_pdf_book_ocr_marks_partial_failure_as_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api_server import create_app
    from src.web.tasks import execute_pdf_book_ocr

    write_minimal_settings(tmp_path)
    input_dir = tmp_path / "data/uploads/pdf-ocr/20260713/group-001"
    input_dir.mkdir(parents=True, exist_ok=True)
    first_pdf = input_dir / "第一册.pdf"
    second_pdf = input_dir / "第二册.pdf"
    first_pdf.write_bytes(b"%PDF-1.4 first")
    second_pdf.write_bytes(b"%PDF-1.4 second")

    app = create_app(project_root=tmp_path)
    task_id = create_pdf_book_ocr_task_id()
    task_paths = build_pdf_book_ocr_task_paths(tmp_path, task_id)
    write_json_file(task_paths.state_path, create_initial_state(task_id, "pdf-ocr"))

    def fake_ocr_pdf_book_batch(source: Path, output_dir: Path, _loaded_settings) -> PDFBookOCRSummary:
        output_path = output_dir / "第一册.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("第一册文本", encoding="utf-8")
        return PDFBookOCRSummary(
            items=[
                PDFBookOCRItem(
                    source_pdf=first_pdf,
                    output_text_path=output_path,
                    success=True,
                    text_length=len("第一册文本"),
                    warnings=[],
                ),
                PDFBookOCRItem(
                    source_pdf=second_pdf,
                    output_text_path=output_dir / "第二册.txt",
                    success=False,
                    text_length=0,
                    warnings=[],
                    error="第二册第 3 页识别失败",
                ),
            ]
        )

    monkeypatch.setattr("src.web.tasks.ocr_pdf_book_batch", fake_ocr_pdf_book_batch)

    execute_pdf_book_ocr(app=app, task_id=task_id, payload={"input_path": str(input_dir)})

    state = read_json_file(task_paths.state_path)
    assert state["status"] == "failed"
    assert state["success"] == 1
    assert state["failed"] == 1
    assert "部分 PDF OCR 失败" in state["error_message"]
    assert state["items"][0]["output_file"] == "第一册.txt"
    assert state["items"][1]["error"] == "第二册第 3 页识别失败"
