from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.probe_asr_backends import check_intervals, json_value


def test_probe_help_does_not_import_optional_dependencies():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts/probe_asr_backends.py"), "--help"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    assert "qwen3-asr-1.7b" in completed.stdout
    assert "fun-asr-nano" in completed.stdout


@pytest.mark.parametrize("intervals", [
    [(-1.0, 1.0)], [(2.0, 1.0)], [(0.0, float("nan"))],
    [(0.0, float("inf"))], [(0.0, 11.0)], [(2.0, 3.0), (1.0, 2.0)],
])
def test_probe_rejects_invalid_raw_timestamps(intervals):
    with pytest.raises(ValueError):
        check_intervals(intervals, duration=10.0)


def test_probe_accepts_real_absolute_intervals():
    check_intervals([(0.1, 2.0), (4.0, 5.0), (9.0, 10.0)], duration=10.0)


def test_probe_preserves_dataclass_sdk_result():
    @dataclass
    class Stamp:
        text: str
        start_time: float
        end_time: float

    assert json_value({"timestamps": [Stamp("字", 1.0, 2.0)]}) == {
        "timestamps": [{"text": "字", "start_time": 1.0, "end_time": 2.0}]
    }
    with pytest.raises(TypeError):
        json_value(object())
