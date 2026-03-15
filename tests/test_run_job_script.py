from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def load_run_job_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts/08_run_job.py"
    spec = importlib.util.spec_from_file_location("run_job_script", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_accepts_backend_and_passes_to_run_single_job(monkeypatch, tmp_path: Path) -> None:
    module = load_run_job_script_module()
    video_path = tmp_path / "lesson.mp4"
    reference_path = tmp_path / "chapter.txt"
    output_dir = tmp_path / "deliverables"
    video_path.write_bytes(b"video")
    reference_path.write_text("参考原文", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "08_run_job.py",
            "--video",
            str(video_path),
            "--reference",
            str(reference_path),
            "--output-dir",
            str(output_dir),
            "--backend",
            "gemini_cli",
        ],
    )

    seen: dict[str, object] = {}
    monkeypatch.setattr(module, "load_settings", lambda **_kwargs: "loaded-settings")

    def fake_run_single_job(**kwargs):
        seen["backend"] = kwargs["backend"]
        return SimpleNamespace(
            job_id="job-fixed",
            job_root=tmp_path / "data/jobs/job-fixed",
            copied_output_path=output_dir / "lesson.md",
        )

    monkeypatch.setattr(module, "run_single_job", fake_run_single_job)

    assert module.main() == 0
    assert seen["backend"] == "gemini_cli"
