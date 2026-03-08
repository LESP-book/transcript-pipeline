from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config_loader import load_settings
from src.export_utils import (
    ExportError,
    ExportInputEmptyError,
    build_markdown_output_path,
    export_markdown_batch,
    iter_refined_json_files,
    render_markdown_document,
    resolve_export_input_paths,
)
from tests.helpers import write_minimal_settings


def write_export_inputs(tmp_path: Path, basename: str = "demo") -> Path:
    refined_dir = tmp_path / "data" / "intermediate" / "refined"
    refined_dir.mkdir(parents=True, exist_ok=True)

    refined_path = refined_dir / f"{basename}.json"

    refined_payload = {
        "source_asr_file": f"data/intermediate/asr/{basename}.txt",
        "source_reference_file": f"data/intermediate/extracted_text/{basename}.txt",
        "refinement_backends": ["codex_cli", "gemini_cli"],
        "backend_status": {
            "codex_cli": "returned_fulltext",
            "gemini_cli": "returned_fulltext",
        },
        "prompt_mode": "fulltext",
        "total_blocks": 4,
        "selected_backend": "gemini_cli",
        "comparison_summary": "selected=gemini_cli:82.1;runner_up=codex_cli:79.9",
        "final_markdown": f"# {basename}\n\n中央人民广播电台现在播送毛主席诗词。\n\n> 久有凌云志，重上井冈山。\n\n## 提问环节\n\n请问这一句是什么意思？",
        "refined_full_text": "中央人民广播电台现在播送毛主席诗词。\n\n久有凌云志，重上井冈山。\n\n请问这一句是什么意思？",
    }
    refined_path.write_text(json.dumps(refined_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return refined_path


def test_iter_refined_json_files_filters_json_only(tmp_path: Path) -> None:
    refined_dir = tmp_path / "data" / "intermediate" / "refined"
    refined_dir.mkdir(parents=True, exist_ok=True)
    (refined_dir / "a.json").write_text("{}", encoding="utf-8")
    (refined_dir / "b.txt").write_text("ignore", encoding="utf-8")

    result = iter_refined_json_files(refined_dir)

    assert [item.name for item in result] == ["a.json"]


def test_build_markdown_output_path_uses_md_extension(tmp_path: Path) -> None:
    output = build_markdown_output_path(tmp_path / "demo.json", tmp_path / "out")
    assert output.markdown_path == tmp_path / "out" / "demo.md"


def test_export_markdown_batch_raises_when_refined_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    with pytest.raises(ExportInputEmptyError):
        export_markdown_batch(loaded_settings)


def test_resolve_export_input_paths_uses_refined_source(tmp_path: Path) -> None:
    settings_path = write_minimal_settings(tmp_path)
    loaded_settings = load_settings(settings_path=settings_path, project_root=tmp_path)
    refined_path = write_export_inputs(tmp_path, basename="sample")
    refined_payload = json.loads(refined_path.read_text(encoding="utf-8"))

    paths = resolve_export_input_paths(refined_path, refined_payload, loaded_settings)

    assert paths.refined_json_path == refined_path


def test_render_markdown_document_creates_final_markdown_without_internal_fields(tmp_path: Path) -> None:
    refined_path = write_export_inputs(tmp_path, basename="sample")
    refined_payload = json.loads(refined_path.read_text(encoding="utf-8"))

    markdown = render_markdown_document(
        refined_payload=refined_payload,
        refined_json_path=refined_path,
    )

    assert "# sample" in markdown
    assert "> 久有凌云志，重上井冈山。" in markdown
    assert "## 提问环节" in markdown
    assert "请问这一句是什么意思？" in markdown
    assert "comparison_summary" not in markdown
    assert "backend_status" not in markdown
    assert "source_reference_file" not in markdown


def test_export_markdown_batch_writes_final_markdown(tmp_path: Path) -> None:
    settings_path = write_minimal_settings(tmp_path)
    loaded_settings = load_settings(settings_path=settings_path, project_root=tmp_path)
    write_export_inputs(tmp_path, basename="lesson")

    summary = export_markdown_batch(loaded_settings)

    output_path = tmp_path / "data" / "output" / "final" / "lesson.md"
    assert summary.total == 1
    assert summary.success == 1
    assert output_path.exists()
    markdown = output_path.read_text(encoding="utf-8")
    assert "# lesson" in markdown
    assert "> 久有凌云志，重上井冈山。" in markdown
    assert "## 提问环节" in markdown


def test_export_markdown_batch_requires_final_markdown(tmp_path: Path) -> None:
    settings_path = write_minimal_settings(tmp_path)
    loaded_settings = load_settings(settings_path=settings_path, project_root=tmp_path)
    refined_dir = tmp_path / "data" / "intermediate" / "refined"
    refined_dir.mkdir(parents=True, exist_ok=True)
    refined_path = refined_dir / "broken.json"
    refined_path.write_text(
        json.dumps({"refined_full_text": "正文"}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ExportError):
        export_markdown_batch(loaded_settings)
