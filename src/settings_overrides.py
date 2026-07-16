from __future__ import annotations

from dataclasses import dataclass

from src.schemas import LoadedSettings

VALID_OCR_BACKENDS = {"codex_api", "codex_cli", "agy"}


class SettingsOverrideError(ValueError):
    """运行时配置覆盖参数无效。"""


@dataclass(frozen=True)
class ModelOverrides:
    llm_model: str | None = None
    llm_reasoning_effort: str | None = None
    ocr_backend: str | None = None
    ocr_model: str | None = None
    ocr_reasoning_effort: str | None = None
    ocr_max_concurrency: int | None = None
    ocr_submit_interval_seconds: float | None = None


def normalize_override_value(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise SettingsOverrideError(f"{label} 不能为空。")
    return normalized


def normalize_ocr_backend(value: str | None) -> str | None:
    normalized = normalize_override_value(value, label="OCR 后端")
    if normalized is not None and normalized not in VALID_OCR_BACKENDS:
        allowed = "、".join(sorted(VALID_OCR_BACKENDS))
        raise SettingsOverrideError(f"OCR 后端必须是以下之一：{allowed}。")
    return normalized


def validate_ocr_scheduling_overrides(
    max_concurrency: int | None,
    submit_interval_seconds: float | None,
) -> None:
    if max_concurrency is not None and max_concurrency < 1:
        raise SettingsOverrideError("PDF OCR 最大并发数必须是正整数。")
    if submit_interval_seconds is not None and submit_interval_seconds < 0:
        raise SettingsOverrideError("PDF OCR 投递间隔不能小于 0 秒。")


def apply_model_overrides(loaded_settings: LoadedSettings, overrides: ModelOverrides) -> None:
    llm_model = normalize_override_value(overrides.llm_model, label="阶段 6 模型")
    llm_reasoning_effort = normalize_override_value(overrides.llm_reasoning_effort, label="阶段 6 reasoning effort")
    ocr_backend = normalize_ocr_backend(overrides.ocr_backend)
    ocr_model = normalize_override_value(overrides.ocr_model, label="OCR 模型")
    ocr_reasoning_effort = normalize_override_value(overrides.ocr_reasoning_effort, label="OCR reasoning effort")
    validate_ocr_scheduling_overrides(
        overrides.ocr_max_concurrency,
        overrides.ocr_submit_interval_seconds,
    )

    if llm_model is not None:
        loaded_settings.settings.llm.model = llm_model
    if llm_reasoning_effort is not None:
        loaded_settings.settings.llm.reasoning_effort = llm_reasoning_effort
    if ocr_backend is not None:
        loaded_settings.settings.reference.ai_ocr_backend = ocr_backend
    if ocr_model is not None:
        loaded_settings.settings.reference.codex_ocr_model = ocr_model
    if ocr_reasoning_effort is not None:
        loaded_settings.settings.reference.codex_ocr_reasoning_effort = ocr_reasoning_effort
    if overrides.ocr_max_concurrency is not None:
        loaded_settings.settings.reference.codex_ocr_max_concurrency = overrides.ocr_max_concurrency
    if overrides.ocr_submit_interval_seconds is not None:
        loaded_settings.settings.reference.codex_ocr_submit_interval_seconds = overrides.ocr_submit_interval_seconds


def apply_model_overrides_to_raw_settings(payload: dict, overrides: ModelOverrides) -> None:
    llm_model = normalize_override_value(overrides.llm_model, label="阶段 6 模型")
    llm_reasoning_effort = normalize_override_value(overrides.llm_reasoning_effort, label="阶段 6 reasoning effort")
    ocr_backend = normalize_ocr_backend(overrides.ocr_backend)
    ocr_model = normalize_override_value(overrides.ocr_model, label="OCR 模型")
    ocr_reasoning_effort = normalize_override_value(overrides.ocr_reasoning_effort, label="OCR reasoning effort")
    validate_ocr_scheduling_overrides(
        overrides.ocr_max_concurrency,
        overrides.ocr_submit_interval_seconds,
    )

    if llm_model is not None or llm_reasoning_effort is not None:
        llm_payload = payload.setdefault("llm", {})
        if not isinstance(llm_payload, dict):
            raise SettingsOverrideError("配置字段 llm 必须是对象，无法覆盖阶段 6 模型。")
        if llm_model is not None:
            llm_payload["model"] = llm_model
        if llm_reasoning_effort is not None:
            llm_payload["reasoning_effort"] = llm_reasoning_effort

    if (
        ocr_backend is not None
        or ocr_model is not None
        or ocr_reasoning_effort is not None
        or overrides.ocr_max_concurrency is not None
        or overrides.ocr_submit_interval_seconds is not None
    ):
        reference_payload = payload.setdefault("reference", {})
        if not isinstance(reference_payload, dict):
            raise SettingsOverrideError("配置字段 reference 必须是对象，无法覆盖 OCR 模型。")
        if ocr_backend is not None:
            reference_payload["ai_ocr_backend"] = ocr_backend
        if ocr_model is not None:
            reference_payload["codex_ocr_model"] = ocr_model
        if ocr_reasoning_effort is not None:
            reference_payload["codex_ocr_reasoning_effort"] = ocr_reasoning_effort
        if overrides.ocr_max_concurrency is not None:
            reference_payload["codex_ocr_max_concurrency"] = overrides.ocr_max_concurrency
        if overrides.ocr_submit_interval_seconds is not None:
            reference_payload["codex_ocr_submit_interval_seconds"] = overrides.ocr_submit_interval_seconds
