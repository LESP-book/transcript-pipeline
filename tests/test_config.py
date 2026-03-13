from __future__ import annotations

from pathlib import Path

from src.config_loader import load_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_settings_success() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT)

    assert loaded_settings.settings.project.name == "transcript-pipeline"
    assert loaded_settings.settings_path == (PROJECT_ROOT / "config/settings.yaml").resolve()
    assert loaded_settings.settings.llm.backends == ["codex_cli"]
    assert loaded_settings.settings.llm.model == "gpt-5.4"
    assert loaded_settings.settings.llm.reasoning_effort == "high"


def test_load_settings_local_cpu_profile() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT, profile_name="local_cpu")

    assert loaded_settings.active_profile_name == "local_cpu"
    assert loaded_settings.active_profile.device == "cpu"
    assert loaded_settings.active_profile.beam_size == 5


def test_load_settings_local_cpu_high_accuracy_profile() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT, profile_name="local_cpu_high_accuracy")

    assert loaded_settings.active_profile_name == "local_cpu_high_accuracy"
    assert loaded_settings.active_profile.device == "cpu"
    assert loaded_settings.active_profile.asr_model_size == "large-v3-turbo"
    assert loaded_settings.active_profile.beam_size == 8


def test_load_settings_wsl2_gpu_profile() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT, profile_name="wsl2_gpu")

    assert loaded_settings.active_profile_name == "wsl2_gpu"
    assert loaded_settings.active_profile.device == "cuda"
    assert loaded_settings.active_profile.asr_model_size == "medium"
    assert loaded_settings.active_profile.beam_size == 5


def test_load_settings_wsl2_gpu_max_accuracy_profile() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT, profile_name="wsl2_gpu_max_accuracy")

    assert loaded_settings.active_profile_name == "wsl2_gpu_max_accuracy"
    assert loaded_settings.active_profile.device == "cuda"
    assert loaded_settings.active_profile.asr_model_size == "large-v3-turbo"
    assert loaded_settings.active_profile.asr_compute_type == "float16"
    assert loaded_settings.active_profile.beam_size == 10


def test_load_settings_wsl2_gpu_high_accuracy_profile() -> None:
    loaded_settings = load_settings(project_root=PROJECT_ROOT, profile_name="wsl2_gpu_high_accuracy")

    assert loaded_settings.active_profile_name == "wsl2_gpu_high_accuracy"
    assert loaded_settings.active_profile.device == "cuda"
    assert loaded_settings.active_profile.asr_model_size == "large-v3-turbo"
    assert loaded_settings.active_profile.beam_size == 8
