from __future__ import annotations

from pathlib import Path

from src.config_loader import load_settings
from src.pipeline_jobs import run_local_preprocess_job
from tests.helpers import write_minimal_settings


def test_run_local_preprocess_job_runs_extract_and_transcribe_with_quality_tier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        "src.pipeline_jobs.extract_audio_batch",
        lambda loaded_settings_arg, logger=None: calls.append(("extract", None)) or ["audio"],
    )
    monkeypatch.setattr(
        "src.pipeline_jobs.transcribe_batch",
        lambda loaded_settings_arg, logger=None, quality_tier_name=None: calls.append(("transcribe", quality_tier_name)) or ["asr"],
    )

    result = run_local_preprocess_job(loaded_settings, quality_tier_name="max")

    assert result.quality_tier_name == "max"
    assert result.extracted_audio == ["audio"]
    assert result.transcribed_audio == ["asr"]
    assert calls == [("extract", None), ("transcribe", "max")]
