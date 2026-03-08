from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AppBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class ProjectSettings(AppBaseModel):
    name: str
    version: str
    description: str


class RuntimeSettings(AppBaseModel):
    profile: str
    environment: str = "local"
    log_level: str = "INFO"


class ProfileSettings(AppBaseModel):
    device: str
    asr_compute_type: str
    asr_model_size: str
    batch_size: int
    temp_dir: str
    cache_dir: str


class PathsSettings(AppBaseModel):
    videos_dir: str
    audio_dir: str
    reference_dir: str
    asr_dir: str
    ocr_dir: str
    extracted_text_dir: str
    chunks_dir: str
    aligned_dir: str
    review_dir: str
    final_dir: str
    logs_dir: str


class AudioSettings(AppBaseModel):
    output_format: str = "wav"
    sample_rate: int = 16000
    channels: int = 1
    overwrite: bool = False
    supported_video_ext: list[str] = Field(default_factory=list)
    supported_audio_ext: list[str] = Field(default_factory=list)

    @field_validator("supported_video_ext", "supported_audio_ext")
    @classmethod
    def normalize_extensions(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            extension = item.strip().lower()
            if not extension.startswith("."):
                extension = f".{extension}"
            normalized.append(extension)
        return normalized


class PromptSettings(AppBaseModel):
    classify_and_correct: str
    final_cleanup: str


class ReferenceSettings(AppBaseModel):
    enabled: bool = True
    allow_pdf: bool = True
    allow_txt: bool = True
    allow_md: bool = True
    allow_docx: bool = False
    prefer_existing_text: bool = True
    run_ocr_when_needed: bool = False
    sentence_split_enabled: bool = True
    ocr_languages: list[str] = Field(default_factory=list)


class AsrSettings(AppBaseModel):
    engine: str
    language: str
    beam_size: int = 5
    vad_filter: bool = False
    condition_on_previous_text: bool = True
    word_timestamps: bool = False
    initial_prompt: str = ""
    model_cache_subdir: str = "faster-whisper"


class SegmentationSettings(AppBaseModel):
    enabled: bool = True
    min_chars_per_block: int = 60
    max_chars_per_block: int = 500
    max_seconds_per_block: float = 30.0
    split_on_empty_line: bool = True
    merge_short_lines: bool = True


class AlignmentSettings(AppBaseModel):
    method: str = "rapidfuzz_ratio"
    top_k: int = 3
    matched_threshold: float = 80.0
    weak_match_threshold: float = 55.0
    use_normalization: bool = True


class AppSettings(AppBaseModel):
    project: ProjectSettings
    runtime: RuntimeSettings
    profiles: dict[str, ProfileSettings]
    paths: PathsSettings
    audio: AudioSettings
    asr: AsrSettings
    reference: ReferenceSettings
    segmentation: SegmentationSettings
    alignment: AlignmentSettings
    prompts: PromptSettings | None = None


@dataclass(frozen=True)
class LoadedSettings:
    settings: AppSettings
    project_root: Path
    settings_path: Path
    active_profile_name: str
    active_profile: ProfileSettings

    def resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()

    def path_for(self, field_name: str) -> Path:
        paths = self.settings.paths.model_dump()
        if field_name not in paths:
            raise KeyError(f"未知路径字段: {field_name}")
        return self.resolve_path(paths[field_name])
