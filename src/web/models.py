from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SingleJobRequest(BaseModel):
    video: str
    reference: str
    output_dir: str
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_api", "codex_cli", "gemini_cli", "both"] | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    ocr_backend: Literal["codex_api", "codex_cli", "gemini_cli"] | None = None
    ocr_model: str | None = None
    ocr_reasoning_effort: str | None = None
    book_name: str | None = None
    chapter: str | None = None
    glossary_file: str | None = None


class BatchJobRequest(BaseModel):
    manifest: str | None = None
    videos_dir: str | None = None
    reference_dir: str | None = None
    shared_reference: str | None = None
    output_dir: str | None = None
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_api", "codex_cli", "gemini_cli", "both"] | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    ocr_backend: Literal["codex_api", "codex_cli", "gemini_cli"] | None = None
    ocr_model: str | None = None
    ocr_reasoning_effort: str | None = None
    glossary_file: str | None = None
    remote_concurrency: int | None = Field(default=None, ge=1)
    book_name: str | None = None
    chapter: str | None = None


class StageRunRequest(BaseModel):
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_api", "codex_cli", "gemini_cli", "both"] | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    ocr_backend: Literal["codex_api", "codex_cli", "gemini_cli"] | None = None
    ocr_model: str | None = None
    ocr_reasoning_effort: str | None = None


class JobRerunRequest(BaseModel):
    start_stage: str
    profile: str | None = None
    backend: Literal["codex_api", "codex_cli", "gemini_cli", "both"] | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    ocr_backend: Literal["codex_api", "codex_cli", "gemini_cli"] | None = None
    ocr_model: str | None = None
    ocr_reasoning_effort: str | None = None
