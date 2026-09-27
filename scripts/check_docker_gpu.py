#!/usr/bin/env python3
"""Check NVIDIA GPU access from inside the running Docker application container."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check container CUDA; optionally transcribe a short audio sample on GPU.")
    parser.add_argument("--audio", type=Path, help="Short audio file mounted inside the container")
    parser.add_argument("--model", default="small", help="faster-whisper model to use with --audio (default: small)")
    args = parser.parse_args()
    sys.path.insert(0, str(PROJECT_ROOT))

    try:
        from src.asr_utils import configure_cuda_runtime_from_venv

        library_dirs = configure_cuda_runtime_from_venv()
    except (ImportError, OSError) as exc:
        print(f"Could not prepare the CUDA wheel runtime: {exc}", file=sys.stderr)
        return 1

    try:
        import ctranslate2
    except ImportError as exc:
        print(f"CTranslate2 could not be imported: {exc}", file=sys.stderr)
        return 1

    print(f"CUDA wheel library directories: {', '.join(map(str, library_dirs)) or '(not found)'}")

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None and Path("/usr/lib/wsl/lib/nvidia-smi").is_file():
        nvidia_smi = "/usr/lib/wsl/lib/nvidia-smi"
    if nvidia_smi:
        result = subprocess.run(
            [nvidia_smi, "-L"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(result.stdout.strip())
        else:
            detail = result.stderr.strip() or result.stdout.strip()
            print(f"nvidia-smi could not query the GPU: {detail or result.returncode}", file=sys.stderr)
    else:
        print("nvidia-smi is not mounted in this container; CTranslate2 is the GPU availability check.")

    try:
        device_count = ctranslate2.get_cuda_device_count()
    except Exception as exc:  # CTranslate2 surfaces driver/runtime discovery errors here.
        print(f"CTranslate2 CUDA device discovery failed: {exc}", file=sys.stderr)
        return 1

    if device_count < 1:
        print(
            "No CUDA device is visible to CTranslate2. Check the host NVIDIA driver/WSL GPU support, "
            "the Docker NVIDIA Container Toolkit/CDI configuration, and the Compose GPU reservation.",
            file=sys.stderr,
        )
        return 1

    try:
        supported_types = sorted(ctranslate2.get_supported_compute_types("cuda"))
    except Exception as exc:
        print(f"Could not query CUDA compute types: {exc}", file=sys.stderr)
        return 1

    print(f"CTranslate2 CUDA device count: {device_count}")
    print(f"CTranslate2 CUDA compute types: {', '.join(supported_types)}")
    if "float16" not in supported_types:
        print("The configured wsl2_gpu profiles require float16, which this device/runtime does not report.", file=sys.stderr)
        return 1

    if args.audio is not None:
        if not args.audio.is_file():
            print(f"Audio sample does not exist: {args.audio}", file=sys.stderr)
            return 1
        try:
            from faster_whisper import WhisperModel

            cache_dir = Path.home() / ".cache/transcript-pipeline/faster-whisper"
            model = WhisperModel(args.model, device="cuda", compute_type="float16", download_root=str(cache_dir))
            raw_segments, _ = model.transcribe(str(args.audio), language="zh", vad_filter=False)
            # Inference is lazy: only consuming the iterator proves CUDA transcription ran.
            segments = list(raw_segments)
        except Exception as exc:
            print(f"CUDA transcription failed (no CPU fallback): {exc}", file=sys.stderr)
            return 1
        if not segments or not any(segment.text.strip() for segment in segments):
            print("Audio produced no non-empty segments; use a short sample containing speech.", file=sys.stderr)
            return 1
        print(f"CUDA transcription consumed {len(segments)} segment(s) with model {args.model}.")
        print("Inspect a separate isolated project ASR JSON/TXT run for content quality; text is not logged here.")

    print("Docker GPU check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
