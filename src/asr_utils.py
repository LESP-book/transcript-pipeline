from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from src.runtime_utils import ensure_directory
from src.schemas import LoadedSettings


class AsrTranscriptionError(RuntimeError):
    """Raised when transcription fails."""


class AsrDependencyError(AsrTranscriptionError):
    """Raised when required ASR dependencies are missing."""


class UnsupportedAsrEngineError(AsrTranscriptionError):
    """Raised when the configured ASR engine is not supported."""


class InvalidAsrDeviceError(AsrTranscriptionError):
    """Raised when the configured ASR device is invalid."""


class CudaUnavailableError(AsrTranscriptionError):
    """Raised when CUDA is requested but unavailable."""


class AsrModelLoadError(AsrTranscriptionError):
    """Raised when the ASR model cannot be loaded."""


class AudioInputEmptyError(AsrTranscriptionError):
    """Raised when there are no supported audio files to transcribe."""


@dataclass(frozen=True)
class AsrSegmentResult:
    id: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class AsrFileResult:
    source_file: str
    engine: str
    model_size: str
    device: str
    compute_type: str
    language: str
    segments: list[AsrSegmentResult]
    full_text: str


@dataclass(frozen=True)
class AsrOutputPaths:
    json_path: Path
    txt_path: Path


@dataclass(frozen=True)
class AsrBatchItem:
    source_audio_path: Path
    output_paths: AsrOutputPaths
    segment_count: int


def normalize_extension(extension: str) -> str:
    normalized = extension.strip().lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized


def iter_audio_files(audio_dir: Path, allowed_extensions: Iterable[str]) -> list[Path]:
    normalized_extensions = {normalize_extension(extension) for extension in allowed_extensions}
    if not audio_dir.exists():
        return []

    return sorted(
        path
        for path in audio_dir.iterdir()
        if path.is_file() and path.suffix.lower() in normalized_extensions
    )


def build_asr_output_paths(audio_path: Path, output_dir: Path) -> AsrOutputPaths:
    return AsrOutputPaths(
        json_path=output_dir / f"{audio_path.stem}.json",
        txt_path=output_dir / f"{audio_path.stem}.txt",
    )


def validate_asr_runtime(loaded_settings: LoadedSettings) -> None:
    engine = loaded_settings.settings.asr.engine.strip().lower()
    device = loaded_settings.active_profile.device.strip().lower()

    if engine != "faster-whisper":
        raise UnsupportedAsrEngineError(
            f"当前阶段仅支持 faster-whisper，配置值为: {loaded_settings.settings.asr.engine}"
        )

    if device not in {"cpu", "cuda"}:
        raise InvalidAsrDeviceError(
            f"无效的 ASR device 配置: {loaded_settings.active_profile.device}. 仅支持 cpu 或 cuda。"
        )


def import_whisper_model_class() -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise AsrDependencyError(
            "未安装 faster-whisper。请先执行 `pip install -r requirements.txt`。"
        ) from exc

    return WhisperModel


def looks_like_cuda_error(message: str) -> bool:
    normalized = message.lower()
    keywords = ("cuda", "cublas", "cudnn", "driver", "gpu", "curand")
    return any(keyword in normalized for keyword in keywords)


def load_faster_whisper_model(loaded_settings: LoadedSettings) -> Any:
    validate_asr_runtime(loaded_settings)
    WhisperModel = import_whisper_model_class()

    profile = loaded_settings.active_profile
    settings = loaded_settings.settings
    model_size = profile.asr_model_size
    device = profile.device.lower()
    compute_type = profile.asr_compute_type
    download_root = loaded_settings.resolve_path(profile.cache_dir) / settings.asr.model_cache_subdir

    try:
        return WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(download_root),
        )
    except Exception as exc:
        message = str(exc)
        if device == "cuda" and looks_like_cuda_error(message):
            raise CudaUnavailableError(
                "当前 profile 配置为 cuda，但运行环境不可用。"
                f" model_size={model_size}, compute_type={compute_type} | {message}"
            ) from exc

        raise AsrModelLoadError(
            "加载 faster-whisper 模型失败。"
            f" model_size={model_size}, device={device}, compute_type={compute_type} | {message}"
        ) from exc


def build_source_file_label(audio_path: Path, loaded_settings: LoadedSettings) -> str:
    try:
        return str(audio_path.resolve().relative_to(loaded_settings.project_root))
    except ValueError:
        return str(audio_path.resolve())


def transcribe_audio_file(
    audio_path: Path,
    model: Any,
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> AsrFileResult:
    profile = loaded_settings.active_profile
    settings = loaded_settings.settings
    beam_size = profile.beam_size if profile.beam_size is not None else settings.asr.beam_size

    try:
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=settings.asr.language,
            beam_size=beam_size,
            vad_filter=settings.asr.vad_filter,
            condition_on_previous_text=settings.asr.condition_on_previous_text,
            word_timestamps=settings.asr.word_timestamps,
            initial_prompt=settings.asr.initial_prompt or None,
        )
        segments = [
            AsrSegmentResult(
                id=int(segment.id),
                start=float(segment.start),
                end=float(segment.end),
                text=segment.text.strip(),
            )
            for segment in list(raw_segments)
        ]
    except Exception as exc:
        if profile.device.lower() == "cuda" and looks_like_cuda_error(str(exc)):
            raise CudaUnavailableError(f"CUDA 转录失败: {audio_path.name} | {exc}") from exc
        raise AsrTranscriptionError(f"转录失败: {audio_path.name} | {exc}") from exc

    language = getattr(info, "language", settings.asr.language) or settings.asr.language
    full_text = "\n".join(segment.text for segment in segments if segment.text).strip()

    if logger:
        logger.info("转录完成 | %s | segments=%s", audio_path.name, len(segments))

    return AsrFileResult(
        source_file=build_source_file_label(audio_path, loaded_settings),
        engine=settings.asr.engine,
        model_size=profile.asr_model_size,
        device=profile.device,
        compute_type=profile.asr_compute_type,
        language=language,
        segments=segments,
        full_text=full_text,
    )


def write_asr_result(result: AsrFileResult, output_paths: AsrOutputPaths) -> None:
    ensure_directory(output_paths.json_path.parent)

    payload = {
        "source_file": result.source_file,
        "engine": result.engine,
        "model_size": result.model_size,
        "device": result.device,
        "compute_type": result.compute_type,
        "language": result.language,
        "segments": [asdict(segment) for segment in result.segments],
        "full_text": result.full_text,
    }

    with output_paths.json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    with output_paths.txt_path.open("w", encoding="utf-8") as file:
        file.write(result.full_text)


def transcribe_batch(
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> list[AsrBatchItem]:
    audio_dir = loaded_settings.path_for("audio_dir")
    output_dir = ensure_directory(loaded_settings.path_for("asr_dir"))
    audio_files = iter_audio_files(audio_dir, loaded_settings.settings.audio.supported_audio_ext)

    if not audio_files:
        supported_ext = ", ".join(loaded_settings.settings.audio.supported_audio_ext)
        raise AudioInputEmptyError(
            f"输入目录中没有可处理的音频文件: {audio_dir}。支持扩展名: {supported_ext}"
        )

    model = load_faster_whisper_model(loaded_settings)
    output_files: list[AsrBatchItem] = []

    for audio_path in audio_files:
        result = transcribe_audio_file(audio_path, model, loaded_settings, logger=logger)
        output_paths = build_asr_output_paths(audio_path, output_dir)
        write_asr_result(result, output_paths)
        output_files.append(
            AsrBatchItem(
                source_audio_path=audio_path,
                output_paths=output_paths,
                segment_count=len(result.segments),
            )
        )

    return output_files


def summarize_transcription_results(output_files: list[AsrBatchItem]) -> str:
    total = len(output_files)
    total_segments = sum(item.segment_count for item in output_files)
    return f"total={total}, json={total}, txt={total}, segments={total_segments}"
