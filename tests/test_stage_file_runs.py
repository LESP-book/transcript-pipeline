from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from src.config_loader import load_settings
from src.web.stage_file_runs import (
    StageFileRunError,
    build_stage_file_workspace,
    build_stage_input_destination,
    build_stage_result_archive,
    place_stage_inputs,
    stage_input_upload_root,
    stage_input_slots,
)
from tests.helpers import write_minimal_settings


def staged_file(project_root: Path, stage_name: str, slot_key: str, filename: str, content: str) -> Path:
    loaded_settings = load_settings(project_root=project_root)
    path = build_stage_input_destination(
        project_root=project_root,
        stage_name=stage_name,
        slot_key=slot_key,
        filename=filename,
        loaded_settings=loaded_settings,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_stage_input_slots_describe_stage_specific_file_contracts(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    assert [(slot.key, slot.extensions) for slot in stage_input_slots("transcribe", loaded_settings)] == [
        ("audio", (".flac", ".m4a", ".mp3", ".wav")),
    ]
    assert [slot.key for slot in stage_input_slots("align", loaded_settings)] == ["asr_json", "reference_txt"]


def test_place_stage_inputs_uses_one_canonical_basename_for_paired_inputs(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    asr_path = staged_file(tmp_path, "align", "asr_json", "recording-07.json", '{"segments": []}')
    reference_path = staged_file(tmp_path, "align", "reference_txt", "chapter-title.txt", "参考文本")
    workspace = build_stage_file_workspace(tmp_path, "run-file-001")

    placed = place_stage_inputs(
        project_root=tmp_path,
        workspace=workspace,
        stage_name="align",
        input_files={"asr_json": str(asr_path), "reference_txt": str(reference_path)},
        loaded_settings=loaded_settings,
    )

    assert placed["asr_json"] == workspace.workspace_root / "intermediate/asr/source.json"
    assert placed["reference_txt"] == workspace.workspace_root / "intermediate/extracted_text/source.txt"
    assert placed["asr_json"].read_text(encoding="utf-8") == '{"segments": []}'
    assert placed["reference_txt"].read_text(encoding="utf-8") == "参考文本"


def test_place_stage_inputs_rejects_paths_outside_stage_upload_root(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    workspace = build_stage_file_workspace(tmp_path, "run-file-002")
    outside_path = tmp_path / "outside.wav"
    outside_path.write_bytes(b"audio")

    with pytest.raises(StageFileRunError, match="暂存文件"):
        place_stage_inputs(
            project_root=tmp_path,
            workspace=workspace,
            stage_name="transcribe",
            input_files={"audio": str(outside_path)},
            loaded_settings=loaded_settings,
        )


def test_build_stage_result_archive_contains_only_current_stage_output(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    workspace = build_stage_file_workspace(tmp_path, "run-file-003")
    workspace.job_paths.intermediate_asr_dir.joinpath("source.txt").write_text("转录结果", encoding="utf-8")
    workspace.workspace_root.joinpath("input/audio/source.wav").write_bytes(b"audio")

    archive_path = build_stage_result_archive(
        workspace=workspace,
        stage_name="transcribe",
        result_name="lesson-asr.zip",
    )

    assert archive_path == workspace.run_root / "result/lesson-asr.zip"
    with ZipFile(archive_path) as archive:
        assert archive.namelist() == ["asr/source.txt"]
        assert archive.read("asr/source.txt").decode("utf-8") == "转录结果"
    assert stage_input_upload_root(tmp_path) == tmp_path / "data/uploads/stage-inputs"
