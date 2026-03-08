from __future__ import annotations

from pathlib import Path

import yaml


def write_minimal_settings(
    project_root: Path,
    *,
    supported_audio_ext: list[str] | None = None,
    reference_overrides: dict | None = None,
    segmentation_overrides: dict | None = None,
    alignment_overrides: dict | None = None,
) -> Path:
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
            "supported_audio_ext": supported_audio_ext or [".wav", ".mp3", ".m4a", ".flac"],
        },
        "asr": {
            "engine": "faster-whisper",
            "language": "zh",
            "beam_size": 5,
            "vad_filter": True,
            "condition_on_previous_text": True,
            "word_timestamps": False,
            "initial_prompt": "",
            "model_cache_subdir": "faster-whisper",
        },
        "reference": {
            "enabled": True,
            "allow_pdf": True,
            "allow_txt": True,
            "allow_md": True,
            "allow_docx": False,
            "prefer_existing_text": True,
            "run_ocr_when_needed": False,
            "sentence_split_enabled": True,
            "ocr_languages": ["chi_sim", "eng"],
        },
        "segmentation": {
            "enabled": True,
            "min_chars_per_block": 60,
            "max_chars_per_block": 500,
            "max_seconds_per_block": 30,
            "split_on_empty_line": True,
            "merge_short_lines": True,
        },
        "alignment": {
            "method": "rapidfuzz_ratio",
            "top_k": 3,
            "matched_threshold": 80,
            "weak_match_threshold": 55,
            "use_normalization": True,
        },
    }

    if reference_overrides:
        payload["reference"].update(reference_overrides)
    if segmentation_overrides:
        payload["segmentation"].update(segmentation_overrides)
    if alignment_overrides:
        payload["alignment"].update(alignment_overrides)

    settings_path = config_dir / "settings.yaml"
    with settings_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
    return settings_path
