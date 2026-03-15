from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def load_batch_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts/09_run_batch_jobs.py"
    spec = importlib.util.spec_from_file_location("run_batch_jobs_script", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_returns_one_when_batch_arguments_are_invalid(monkeypatch) -> None:
    module = load_batch_script_module()
    monkeypatch.setattr(sys, "argv", ["09_run_batch_jobs.py"])

    assert module.main() == 1


def test_main_accepts_backend_and_passes_to_run_batch_jobs(monkeypatch, tmp_path: Path) -> None:
    module = load_batch_script_module()
    output_dir = tmp_path / "deliverables"
    output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "09_run_batch_jobs.py",
            "--videos-dir",
            str(tmp_path / "videos"),
            "--shared-reference",
            str(tmp_path / "shared.txt"),
            "--output-dir",
            str(output_dir),
            "--backend",
            "both",
        ],
    )

    seen: dict[str, object] = {}
    monkeypatch.setattr(module, "load_settings", lambda **_kwargs: "loaded-settings")
    monkeypatch.setattr(module, "load_batch_job_specs", lambda **_kwargs: ([], []))

    def fake_run_batch_jobs(**kwargs):
        seen["backend"] = kwargs["backend_override"]
        return SimpleNamespace(batch_id="batch-fixed", total=0, success=0, failed=0)

    monkeypatch.setattr(module, "run_batch_jobs", fake_run_batch_jobs)
    monkeypatch.setattr(module, "get_batch_exit_code", lambda summary: 0)

    assert module.main() == 0
    assert seen["backend"] == "both"
