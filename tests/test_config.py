from __future__ import annotations

from pathlib import Path

from src.config_loader import load_settings
from tests.helpers import write_minimal_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_settings_success() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT)

    assert loaded_settings.settings.project.name == "transcript-pipeline"
    assert loaded_settings.settings_path == (PROJECT_ROOT / "config/settings.yaml").resolve()


def test_load_settings_local_cpu_profile() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT, profile_name="local_cpu")

    assert loaded_settings.active_profile_name == "local_cpu"
    assert loaded_settings.active_profile.device == "cpu"


def test_load_settings_resolves_general_quality_tier_by_device(tmp_path: Path) -> None:
    write_minimal_settings(
        tmp_path,
        profiles_overrides={
            "windows_gpu": {
                "device": "cuda",
                "asr_compute_type": "float16",
                "asr_model_size": "medium",
                "batch_size": 2,
                "temp_dir": "/tmp/transcript-pipeline",
                "cache_dir": "~/.cache/transcript-pipeline",
            }
        },
        runtime_overrides={"profile": "windows_gpu"},
    )

    loaded_settings = load_settings(project_root=tmp_path)
    resolved = loaded_settings.resolve_asr_runtime()

    assert resolved.quality_tier_name == "general"
    assert resolved.device == "cuda"
    assert resolved.compute_type == "float16"
    assert resolved.model_size == "medium"
    assert resolved.beam_size == 5


def test_load_settings_resolves_max_quality_tier_override(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)

    loaded_settings = load_settings(project_root=tmp_path)
    resolved = loaded_settings.resolve_asr_runtime("max")

    assert resolved.quality_tier_name == "max"
    assert resolved.device == "cpu"
    assert resolved.compute_type == "int8"
    assert resolved.model_size == "large-v3-turbo"
    assert resolved.beam_size == 8
