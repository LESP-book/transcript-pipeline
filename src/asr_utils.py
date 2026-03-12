from __future__ import annotations

import ctypes
import importlib.util
import json
import logging
import os
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


CUDA_RUNTIME_PACKAGE_NAMES = ("nvidia.cublas.lib", "nvidia.cudnn.lib")
CUDA_RUNTIME_LIBRARY_FILENAMES = (
    "libcublas.so.12",
    "libcublasLt.so.12",
    "libcudnn.so.9",
)


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


def find_python_package_dirs(package_name: str) -> list[Path]:
    spec = importlib.util.find_spec(package_name)
    if spec is None:
        return []

    if spec.submodule_search_locations:
        return [Path(location).resolve() for location in spec.submodule_search_locations]

    if spec.origin:
        return [Path(spec.origin).resolve().parent]

    return []


def discover_cuda_runtime_library_dirs() -> list[Path]:
    library_dirs: list[Path] = []
    seen: set[Path] = set()

    for package_name in CUDA_RUNTIME_PACKAGE_NAMES:
        for directory in find_python_package_dirs(package_name):
            if directory.exists() and directory not in seen:
                library_dirs.append(directory)
                seen.add(directory)

    return library_dirs


def prepend_ld_library_path(library_dirs: Iterable[Path]) -> str:
    existing_value = os.environ.get("LD_LIBRARY_PATH", "")
    existing_parts = [part for part in existing_value.split(":") if part]
    combined_parts: list[str] = []

    for directory in library_dirs:
        candidate = str(directory)
        if candidate not in combined_parts and candidate not in existing_parts:
            combined_parts.append(candidate)

    combined_parts.extend(existing_parts)
    if combined_parts:
        os.environ["LD_LIBRARY_PATH"] = ":".join(combined_parts)

    return os.environ.get("LD_LIBRARY_PATH", "")


def preload_cuda_runtime_libraries(library_dirs: Iterable[Path]) -> None:
    for library_name in CUDA_RUNTIME_LIBRARY_FILENAMES:
        for directory in library_dirs:
            candidate = directory / library_name
            if not candidate.exists():
                continue
            ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
            break


def configure_cuda_runtime_from_venv() -> list[Path]:
    library_dirs = discover_cuda_runtime_library_dirs()
    if not library_dirs:
        return []

    prepend_ld_library_path(library_dirs)
    preload_cuda_runtime_libraries(library_dirs)
    return library_dirs


def build_cuda_runtime_fix_hint() -> str:
    library_dirs = discover_cuda_runtime_library_dirs()
    if library_dirs:
        joined_dirs = ":".join(str(path) for path in library_dirs)
        return (
            "检测到当前 .venv 已安装 NVIDIA CUDA runtime wheels。"
            f" 若仍失败，请先执行 `export LD_LIBRARY_PATH=\"{joined_dirs}"
            "${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\"` 后重试；"
            "如果当前机器没有可用 GPU，也可以改用 `--profile local_cpu_high_accuracy`。"
        )

    return (
        "当前未发现可用的 NVIDIA CUDA runtime wheels。"
        " 如需继续使用 GPU，请在 .venv 中安装 "
        "`nvidia-cublas-cu12` 和 `nvidia-cudnn-cu12==9.*`，"
        "或改用 `--profile local_cpu_high_accuracy`。"
    )


def looks_like_cuda_error(message: str) -> bool:
    normalized = message.lower()
    keywords = ("cuda", "cublas", "cudnn", "driver", "gpu", "curand")
    return any(keyword in normalized for keyword in keywords)


def load_faster_whisper_model(loaded_settings: LoadedSettings) -> Any:
    validate_asr_runtime(loaded_settings)
    profile = loaded_settings.active_profile
    settings = loaded_settings.settings
    model_size = profile.asr_model_size
    device = profile.device.lower()
    compute_type = profile.asr_compute_type
    download_root = loaded_settings.resolve_path(profile.cache_dir) / settings.asr.model_cache_subdir
    cuda_runtime_hint = build_cuda_runtime_fix_hint()

    if device == "cuda":
        try:
            configure_cuda_runtime_from_venv()
        except OSError as exc:
            raise CudaUnavailableError(
                "CUDA runtime 预加载失败。"
                f" model_size={model_size}, compute_type={compute_type} | {exc}. "
                f"{cuda_runtime_hint}"
            ) from exc

    WhisperModel = import_whisper_model_class()

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
                f" model_size={model_size}, compute_type={compute_type} | {message}. "
                f"{cuda_runtime_hint}"
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
            raise CudaUnavailableError(
                f"CUDA 转录失败: {audio_path.name} | {exc}. {build_cuda_runtime_fix_hint()}"
            ) from exc
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
