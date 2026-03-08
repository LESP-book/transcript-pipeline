from __future__ import annotations

from pathlib import Path

import pytest

from src.config_loader import load_settings
from src.ffmpeg_utils import InputDirectoryEmptyError, extract_audio_batch, iter_video_files
from tests.helpers import write_minimal_settings


def test_extract_audio_batch_raises_when_input_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path, supported_audio_ext=[".wav"])
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
