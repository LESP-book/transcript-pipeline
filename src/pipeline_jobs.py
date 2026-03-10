from __future__ import annotations

import logging
from dataclasses import dataclass

from src.asr_utils import transcribe_batch
from src.ffmpeg_utils import extract_audio_batch
from src.schemas import LoadedSettings


@dataclass(frozen=True)
class LocalPreprocessResult:
    quality_tier_name: str
    extracted_audio: list
    transcribed_audio: list


def run_local_preprocess_job(
    loaded_settings: LoadedSettings,
    *,
    quality_tier_name: str | None = None,
    logger: logging.Logger | None = None,
) -> LocalPreprocessResult:
    selected_quality_tier = quality_tier_name or loaded_settings.settings.asr.quality_tier
    extracted_audio = extract_audio_batch(loaded_settings, logger=logger)
    transcribed_audio = transcribe_batch(
        loaded_settings,
        logger=logger,
        quality_tier_name=selected_quality_tier,
    )
    return LocalPreprocessResult(
        quality_tier_name=selected_quality_tier,
        extracted_audio=extracted_audio,
        transcribed_audio=transcribed_audio,
    )
