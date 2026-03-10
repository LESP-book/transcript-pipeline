from __future__ import annotations

from pathlib import Path

from src.config_loader import load_settings
from src.job_runner import JobResult
from src.server_refine_cli import main
from tests.helpers import write_minimal_settings


def test_server_refine_cli_main_runs_job_and_prints_output(tmp_path: Path, monkeypatch, capsys) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    def fake_run_server_refine_job(**kwargs) -> JobResult:
        assert kwargs["project_root"] == tmp_path
        assert kwargs["base_loaded_settings"].active_profile_name == loaded_settings.active_profile_name
        return JobResult(
            job_id="job-cli",
            job_root=tmp_path / "data/jobs/job-cli",
            generated_settings_path=tmp_path / "data/jobs/job-cli/settings.generated.yaml",
            final_markdown_path=tmp_path / "data/jobs/job-cli/output/final/source.md",
            copied_output_path=tmp_path / "deliverables/out.md",
        )

    monkeypatch.setattr("src.server_refine_cli.load_settings", lambda **kwargs: loaded_settings)
    monkeypatch.setattr("src.server_refine_cli.run_server_refine_job", fake_run_server_refine_job)

    exit_code = main(
        [
            "--asr-json",
            str(tmp_path / "meeting.json"),
            "--asr-text",
            str(tmp_path / "meeting.txt"),
            "--reference",
            str(tmp_path / "chapter.txt"),
            "--output-dir",
            str(tmp_path / "deliverables"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "job=job-cli" in captured.out
