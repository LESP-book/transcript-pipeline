from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest


def load_run_pipeline_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts/run_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_pipeline_script", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_stage_logs_stage_elapsed_time(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = load_run_pipeline_script_module()
    logger = logging.getLogger("test-run-stage")
    loaded_settings = object()

    moments = iter([30.0, 31.25])
    monkeypatch.setattr(module.time, "perf_counter", lambda: next(moments))
    monkeypatch.setattr(module, "extract_audio_batch", lambda _loaded_settings, logger=None: ["ok"])
    monkeypatch.setattr(module, "summarize_extraction_results", lambda _results: "total=1")

    with caplog.at_level("INFO"):
        exit_code = module.run_stage("extract-audio", loaded_settings, logger)

    assert exit_code == 0
    messages = [record.message for record in caplog.records]
    assert any("流水线完成 | stage=extract-audio | total=1 | elapsed=1.250s" in message for message in messages)
