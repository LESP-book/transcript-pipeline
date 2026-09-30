"""One selected PyTorch backend per stage process, isolated from CTranslate2."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
import time
from pathlib import Path

from src.asr.registry import get_candidate


def execute(request: dict) -> list[dict]:
    import numpy as np
    import torch

    candidate = get_candidate(request["candidate"])
    if request["device"] == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用；不自动改用 CPU")
    torch.set_num_threads(4)
    if request["device"] == "cuda":
        torch.cuda.reset_peak_memory_stats()
    backend = None
    versions = {"python": sys.version.split()[0], "torch_cuda": torch.version.cuda}
    load_seconds = None
    for package in ["qwen-asr", "funasr", "torch", "torchaudio", "transformers", "numpy"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    outputs = []
    for item in request["audio"]:
        decoded = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                                  "-i", item["path"], "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
                                 capture_output=True, check=True)
        audio = np.frombuffer(decoded.stdout, dtype="<f4").copy()
        if not len(audio):
            raise ValueError(f"空音频: {item['path']}")
        if not np.isfinite(audio).all():
            raise ValueError(f"音频包含非有限 PCM: {item['path']}")
        duration = len(audio) / 16000
        metadata = {
            "candidate": candidate.id, "model_id": candidate.model, "model_revision": candidate.revision,
            "runtime_versions": versions, "worker_python": sys.executable, "duration_seconds": duration,
            "silence_detection": "faster-whisper CPU Silero VAD (whole-file gate and recorded speech regions)",
            "speech_regions_seconds": [[r["start"] / 16000, r["end"] / 16000]
                                       for r in item["speech_regions_samples"]],
            "warnings": list(request["warnings"]),
        }
        if item["speech_detected"]:
            if backend is None:
                loading = time.monotonic()
                if candidate.engine == "qwen-asr":
                    from src.asr.qwen3_backend import QwenBackend
                    backend = QwenBackend(candidate, request["device"], Path(request["cache"]), request["parameters"])
                else:
                    from src.asr.funasr_backend import FunasrBackend
                    backend = FunasrBackend(candidate, request["device"], Path(request["cache"]), request["parameters"])
                load_seconds = time.monotonic() - loading
            inference = time.monotonic()
            segments, details = backend.transcribe(audio, 16000, duration, request["terms"],
                                                  item["speech_regions_samples"])
            if not segments:
                raise ValueError("VAD 检测到语音，但模型返回空转录；拒绝将其标记为静音成功")
            metadata["warnings"].extend(details.pop("warnings", []))
            metadata.update(details, audio_kind="speech", inference_performed=True,
                            torch_num_threads=4, model_load_shared_for_stage=True,
                            peak_memory_scope="stage_cumulative_including_model_load",
                            model_load_seconds=load_seconds, inference_seconds=time.monotonic() - inference,
                            peak_torch_allocated_bytes=torch.cuda.max_memory_allocated() if request["device"] == "cuda" else None)
        else:
            segments = []
            metadata.update(audio_kind=item["audio_kind"], inference_performed=False,
                            timestamp_source="none", timestamp_granularity="none")
        outputs.append({
            "source_file": item["source_file"], "engine": candidate.engine, "model_size": candidate.model,
            "device": request["device"], "compute_type": (
                "float16" if request["device"] == "cuda" else "float32"
            ) if candidate.engine == "qwen-asr" else (
                "encoder=float32,decoder=bf16" if candidate.id == "fun-asr-nano" and request["device"] == "cuda" else "float32"
            ),
            "language": "zh", "segments": segments,
            "full_text": "\n".join(s["text"] for s in segments if s["text"]).strip(), "metadata": metadata,
        })
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--response", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    response = execute(request)
    args.response.write_text(json.dumps(response, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
