from __future__ import annotations

from pathlib import Path

from src.config_loader import load_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_settings_success() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT)

    assert loaded_settings.settings.project.name == "transcript-pipeline"
    assert loaded_settings.settings_path == (PROJECT_ROOT / "config/settings.yaml").resolve()


def test_load_settings_local_cpu_profile() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT, profile_name="local_cpu")

    assert loaded_settings.active_profile_name == "local_cpu"
    assert loaded_settings.active_profile.device == "cpu"
