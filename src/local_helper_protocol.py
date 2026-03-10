from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelperRuntimeStatus:
    helper_version: str
    gpu_available: bool
    selected_runtime: str
    model_cache_ready: bool


@dataclass(frozen=True)
class CreateLocalJobRequest:
    quality_tier: str
    video_handle: str
    reference_mode: str
    reference_value: str
    local_session_secret: str


@dataclass(frozen=True)
class CreateLocalJobResponse:
    local_job_id: str
    accepted: bool
    message: str
