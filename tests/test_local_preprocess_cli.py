from __future__ import annotations

from pathlib import Path

from src.config_loader import load_settings
from tests.helpers import write_minimal_settings


def test_local_preprocess_cli_forwards_quality_tier(tmp_path: Path, monkeypatch, capsys) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr("src.local_preprocess_cli.load_settings", lambda **kwargs: loaded_settings)

    def fake_run_local_preprocess_job(loaded_settings_arg, logger=None, quality_tier_name=None):
        _ = loaded_settings_arg, logger
        assert quality_tier_name == "high"

        class Result:
            quality_tier_name = "high"
            extracted_audio = ["audio"]
            transcribed_audio = ["asr"]

        return Result()

    monkeypatch.setattr("src.local_preprocess_cli.run_local_preprocess_job", fake_run_local_preprocess_job)

    module = __import__("src.local_preprocess_cli", fromlist=["main"])
    exit_code = module.main(["--quality-tier", "high"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "quality_tier=high" in captured.out
