from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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
