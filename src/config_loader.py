from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.schemas import AppSettings, LoadedSettings

DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


class ConfigLoadError(RuntimeError):
    """Raised when the settings file cannot be loaded."""


class ProfileNotFoundError(ConfigLoadError):
    """Raised when the requested profile does not exist."""


def get_default_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_settings_path(
    settings_path: str | Path | None,
    project_root: Path,
) -> Path:
    env_override = os.getenv("TRANSCRIPT_SETTINGS_PATH")
    candidate = Path(settings_path or env_override or DEFAULT_SETTINGS_PATH)
    if candidate.is_absolute():
        return candidate
    return (project_root / candidate).resolve()


def load_settings(
    settings_path: str | Path | None = None,
    profile_name: str | None = None,
    project_root: str | Path | None = None,
) -> LoadedSettings:
    root = Path(project_root).resolve() if project_root else get_default_project_root()
    resolved_settings_path = resolve_settings_path(settings_path, root)

    if not resolved_settings_path.exists():
        raise ConfigLoadError(
            f"配置文件不存在: {resolved_settings_path}. "
            "请确认已创建 config/settings.yaml，或通过 TRANSCRIPT_SETTINGS_PATH / --config 指定正确路径。"
        )

    try:
        with resolved_settings_path.open("r", encoding="utf-8") as file:
            raw_settings = yaml.safe_load(file)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"配置文件 YAML 解析失败: {resolved_settings_path} | {exc}") from exc
    except OSError as exc:
        raise ConfigLoadError(f"无法读取配置文件: {resolved_settings_path}") from exc

    if not isinstance(raw_settings, dict):
        raise ConfigLoadError(f"配置文件内容无效: {resolved_settings_path} 顶层必须是映射对象。")

    try:
        settings = AppSettings.model_validate(raw_settings)
    except ValidationError as exc:
        raise ConfigLoadError(f"配置字段校验失败: {resolved_settings_path} | {exc}") from exc

    selected_profile = profile_name or os.getenv("TRANSCRIPT_PROFILE") or settings.runtime.profile
    active_profile = settings.profiles.get(selected_profile)
    if active_profile is None:
        available_profiles = ", ".join(sorted(settings.profiles.keys()))
        raise ProfileNotFoundError(
            f"配置 profile 不存在: {selected_profile}. 可用 profile: {available_profiles}"
        )

    return LoadedSettings(
        settings=settings,
        project_root=root,
        settings_path=resolved_settings_path,
        active_profile_name=selected_profile,
        active_profile=active_profile,
    )
