from __future__ import annotations

import pytest

from src.config_loader import load_settings
from src.settings_overrides import ModelOverrides, SettingsOverrideError, apply_model_overrides
from tests.helpers import write_minimal_settings


def test_apply_model_overrides_updates_llm_and_ocr_settings(tmp_path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    apply_model_overrides(
        loaded_settings,
        ModelOverrides(
            llm_model="gpt-5.5",
            llm_reasoning_effort="medium",
            ocr_model="gpt-5.4-mini",
            ocr_reasoning_effort="high",
        ),
    )

    assert loaded_settings.settings.llm.model == "gpt-5.5"
    assert loaded_settings.settings.llm.reasoning_effort == "medium"
    assert loaded_settings.settings.reference.codex_ocr_model == "gpt-5.4-mini"
    assert loaded_settings.settings.reference.codex_ocr_reasoning_effort == "high"


def test_apply_model_overrides_rejects_empty_values(tmp_path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    with pytest.raises(SettingsOverrideError):
        apply_model_overrides(loaded_settings, ModelOverrides(llm_model=" "))
