from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, Field

from src.config_loader import ConfigLoadError, load_settings

SETTINGS_RELATIVE_PATH = Path("data/jobs/frontend-settings.json")


class FrontendSettings(BaseModel):
    codex_lb_base_url: str = ""
    codex_lb_api_key: str = ""
    profile: str = ""
    backend: str = ""
    remote_concurrency: int = Field(default=2, ge=1)
    book_name: str = ""
    chapter: str = ""
    glossary_file: str = ""
    model: str = ""
    reasoning_effort: str = ""
    ocr_backend: str = ""
    ocr_model: str = ""
    ocr_reasoning_effort: str = ""


class FrontendSettingsUpdate(BaseModel):
    codex_lb_base_url: str | None = None
    codex_lb_api_key: str | None = None
    clear_codex_lb_api_key: bool = False
    profile: str | None = None
    backend: str | None = None
    remote_concurrency: int | None = Field(default=None, ge=1)
    book_name: str | None = None
    chapter: str | None = None
    glossary_file: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    ocr_backend: str | None = None
    ocr_model: str | None = None
    ocr_reasoning_effort: str | None = None


def frontend_settings_path(project_root: Path) -> Path:
    return project_root / SETTINGS_RELATIVE_PATH


def normalize_setting_value(value: str | None) -> str:
    return (value or "").strip()


def load_frontend_settings(project_root: Path) -> FrontendSettings:
    path = frontend_settings_path(project_root)
    if not path.exists():
        return FrontendSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return FrontendSettings()
    if not isinstance(payload, dict):
        return FrontendSettings()
    return FrontendSettings.model_validate(payload)


def save_frontend_settings(project_root: Path, update: FrontendSettingsUpdate) -> FrontendSettings:
    current = load_frontend_settings(project_root)
    payload = current.model_dump()

    for field_name in (
        "codex_lb_base_url",
        "profile",
        "backend",
        "book_name",
        "chapter",
        "glossary_file",
        "model",
        "reasoning_effort",
        "ocr_backend",
        "ocr_model",
        "ocr_reasoning_effort",
    ):
        raw_value = getattr(update, field_name)
        if raw_value is not None:
            payload[field_name] = normalize_setting_value(raw_value)
    if update.remote_concurrency is not None:
        payload["remote_concurrency"] = update.remote_concurrency

    if update.clear_codex_lb_api_key:
        payload["codex_lb_api_key"] = ""
    elif update.codex_lb_api_key is not None:
        normalized_api_key = normalize_setting_value(update.codex_lb_api_key)
        if normalized_api_key:
            payload["codex_lb_api_key"] = normalized_api_key

    settings = FrontendSettings.model_validate(payload)
    path = frontend_settings_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return settings


def frontend_settings_response(project_root: Path) -> dict[str, object]:
    settings = load_frontend_settings(project_root)
    try:
        loaded_settings = load_settings(project_root=project_root)
        codex_lb = loaded_settings.settings.codex_lb
        default_base_url = os.environ.get(codex_lb.base_url_env, "").strip() or codex_lb.base_url
        default_profile = loaded_settings.active_profile_name
        configured_backends = loaded_settings.settings.llm.backends
        default_backend = configured_backends[0] if configured_backends else ""
        default_model = loaded_settings.settings.llm.model
        default_reasoning_effort = loaded_settings.settings.llm.reasoning_effort
        default_ocr_backend = loaded_settings.settings.reference.ai_ocr_backend
        default_ocr_model = loaded_settings.settings.reference.codex_ocr_model
        default_ocr_reasoning_effort = loaded_settings.settings.reference.codex_ocr_reasoning_effort
        default_ocr_max_concurrency = loaded_settings.settings.reference.codex_ocr_max_concurrency
        default_ocr_submit_interval_seconds = loaded_settings.settings.reference.codex_ocr_submit_interval_seconds
        api_key_env = codex_lb.api_key_env
        has_env_api_key = bool(os.environ.get(api_key_env, "").strip())
    except ConfigLoadError:
        # 前端设置接口沿用既有稳定响应结构；配置暂时不可读时使用产品明确指定的 OCR 调度默认值。
        default_base_url = ""
        default_profile = ""
        default_backend = ""
        default_model = ""
        default_reasoning_effort = ""
        default_ocr_backend = ""
        default_ocr_model = ""
        default_ocr_reasoning_effort = ""
        default_ocr_max_concurrency = 40
        default_ocr_submit_interval_seconds = 5.0
        api_key_env = "CODEX_LB_API_KEY"
        has_env_api_key = bool(os.environ.get(api_key_env, "").strip())

    return {
        "codex_lb_base_url": settings.codex_lb_base_url or default_base_url,
        "codex_lb_api_key": "",
        "has_codex_lb_api_key": bool(settings.codex_lb_api_key or has_env_api_key),
        "profile": settings.profile or default_profile,
        "backend": settings.backend or default_backend,
        "remote_concurrency": settings.remote_concurrency,
        "book_name": settings.book_name,
        "chapter": settings.chapter,
        "glossary_file": settings.glossary_file,
        "model": settings.model or default_model,
        "reasoning_effort": settings.reasoning_effort or default_reasoning_effort,
        "ocr_backend": settings.ocr_backend or default_ocr_backend,
        "ocr_model": settings.ocr_model or default_ocr_model,
        "ocr_reasoning_effort": settings.ocr_reasoning_effort or default_ocr_reasoning_effort,
        "ocr_max_concurrency": default_ocr_max_concurrency,
        "ocr_submit_interval_seconds": default_ocr_submit_interval_seconds,
        "api_key_env": api_key_env,
        "settings_path": str(frontend_settings_path(project_root)),
    }


@contextmanager
def codex_lb_environment(settings: FrontendSettings) -> Iterator[None]:
    keys = ("CODEX_LB_BASE_URL", "CODEX_LB_API_KEY")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        if settings.codex_lb_base_url:
            os.environ["CODEX_LB_BASE_URL"] = settings.codex_lb_base_url
        if settings.codex_lb_api_key:
            os.environ["CODEX_LB_API_KEY"] = settings.codex_lb_api_key
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
