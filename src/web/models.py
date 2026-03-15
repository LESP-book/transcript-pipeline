from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SingleJobRequest(BaseModel):
    video: str
    reference: str
    output_dir: str
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_cli", "gemini_cli", "both"] | None = None
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
    backend: Literal["codex_cli", "gemini_cli", "both"] | None = None
    glossary_file: str | None = None
    remote_concurrency: int = Field(default=2, ge=1)
    book_name: str | None = None
    chapter: str | None = None


class StageRunRequest(BaseModel):
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_cli", "gemini_cli", "both"] | None = None
