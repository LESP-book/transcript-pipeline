from __future__ import annotations

from pathlib import Path

import pytest

from src.asr_utils import AudioInputEmptyError, build_asr_output_paths, iter_audio_files, transcribe_batch
from src.config_loader import load_settings
from tests.helpers import write_minimal_settings


def test_transcribe_batch_raises_when_audio_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    (tmp_path / "data/input/audio").mkdir(parents=True, exist_ok=True)

    loaded_settings = load_settings(project_root=tmp_path)

    with pytest.raises(AudioInputEmptyError):
        transcribe_batch(loaded_settings)


def test_iter_audio_files_filters_supported_extensions(tmp_path: Path) -> None:
    (tmp_path / "chapter01.wav").write_text("placeholder", encoding="utf-8")
    (tmp_path / "chapter02.MP3").write_text("placeholder", encoding="utf-8")
    (tmp_path / "chapter03.m4a").write_text("placeholder", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("placeholder", encoding="utf-8")

    files = iter_audio_files(tmp_path, [".wav", ".mp3", ".m4a", ".flac"])

    assert [path.name for path in files] == ["chapter01.wav", "chapter02.MP3", "chapter03.m4a"]


def test_build_asr_output_paths_uses_audio_basename(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting-session.wav"
    output_dir = tmp_path / "data/intermediate/asr"

    output_paths = build_asr_output_paths(audio_path, output_dir)

    assert output_paths.json_path == output_dir / "meeting-session.json"
    assert output_paths.txt_path == output_dir / "meeting-session.txt"
