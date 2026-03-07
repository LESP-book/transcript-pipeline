from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.config_loader import load_settings
from src.ffmpeg_utils import InputDirectoryEmptyError, extract_audio_batch, iter_video_files


def write_minimal_settings(project_root: Path) -> Path:
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "project": {
            "name": "transcript-pipeline",
            "version": "0.1.0",
            "description": "test",
        },
        "runtime": {
            "profile": "local_cpu",
            "environment": "test",
            "log_level": "INFO",
        },
        "profiles": {
            "local_cpu": {
                "device": "cpu",
                "asr_compute_type": "int8",
                "asr_model_size": "small",
                "batch_size": 1,
                "temp_dir": "/tmp/transcript-pipeline",
                "cache_dir": "~/.cache/transcript-pipeline",
            }
        },
        "paths": {
            "videos_dir": "data/input/videos",
            "audio_dir": "data/input/audio",
            "reference_dir": "data/input/reference",
            "asr_dir": "data/intermediate/asr",
            "ocr_dir": "data/intermediate/ocr",
            "extracted_text_dir": "data/intermediate/extracted_text",
            "chunks_dir": "data/intermediate/chunks",
            "aligned_dir": "data/intermediate/aligned",
            "review_dir": "data/output/review",
            "final_dir": "data/output/final",
            "logs_dir": "data/output/logs",
        },
        "audio": {
            "output_format": "wav",
            "sample_rate": 16000,
            "channels": 1,
            "overwrite": False,
            "supported_video_ext": [".mp4", ".mkv", ".mov", ".webm"],
            "supported_audio_ext": [".wav"],
        },
    }

    settings_path = config_dir / "settings.yaml"
    with settings_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
    return settings_path


def test_extract_audio_batch_raises_when_input_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    (tmp_path / "data/input/videos").mkdir(parents=True, exist_ok=True)

    loaded_settings = load_settings(project_root=tmp_path)

    with pytest.raises(InputDirectoryEmptyError):
        extract_audio_batch(loaded_settings)


def test_iter_video_files_filters_supported_extensions(tmp_path: Path) -> None:
    (tmp_path / "session01.mp4").write_text("placeholder", encoding="utf-8")
    (tmp_path / "session02.MKV").write_text("placeholder", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("placeholder", encoding="utf-8")
    (tmp_path / "cover.jpeg").write_text("placeholder", encoding="utf-8")

    files = iter_video_files(tmp_path, [".mp4", ".mkv", ".mov", ".webm"])

    assert [path.name for path in files] == ["session01.mp4", "session02.MKV"]
