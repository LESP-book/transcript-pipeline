"""Real-model ASR spike, deliberately separate from pipeline/job output.

Run in the optional ASR environment. Model paths must point to reviewed, pinned
snapshots; this command never downloads weights or falls back to another model.
It saves raw SDK results and timing evidence, not a claimed pipeline deliverable.
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.metadata
import json
import math
import time
from pathlib import Path
from typing import Any


CANDIDATES = {
    "qwen3-asr-1.7b": "qwen17",
    "qwen3-asr-0.6b": "qwen06",
    "paraformer-zh": "paraformer",
    "fun-asr-nano": "nano",
}


def json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return json_value(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"Cannot preserve raw result of type {type(value).__name__}")


def check_intervals(intervals: list[tuple[float, float]], duration: float) -> None:
    previous_start = -1.0
    for start, end in intervals:
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError("Non-finite SDK timestamp")
        if not (0 <= start <= end <= duration + 0.1) or start < previous_start:
            raise ValueError(f"Invalid SDK timestamp: {start}, {end}; duration={duration}")
        previous_start = start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, choices=CANDIDATES)
    parser.add_argument("--model-paths", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--nano-dtype", choices=["fp32", "fp16", "bf16"], default="fp32")
    parser.add_argument("--expect-silence", action="store_true", help="Validate a zero-valued PCM silence input")
    parser.add_argument("--chunk-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite existing spike evidence; choose a new output")
    if not 0 < args.chunk_seconds <= 30:
        parser.error("chunk-seconds must be in (0, 30]")
    if args.max_new_tokens <= 0:
        parser.error("max-new-tokens must be positive")

    import soundfile as sf
    import torch

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable; no automatic CPU fallback")
    torch.set_num_threads(4)
    audio, sample_rate = sf.read(args.audio, dtype="float32")
    if sample_rate != 16000 or audio.ndim != 1 or len(audio) == 0:
        raise ValueError("Spike input must be nonempty mono 16kHz audio")
    duration = len(audio) / sample_rate
    if args.expect_silence and abs(audio).max() > 1e-7:
        raise ValueError("expect-silence requires zero-valued PCM, not an assumed quiet recording")
    paths = json.loads(args.model_paths.read_text())
    model_path = paths[CANDIDATES[args.candidate]]
    device = "cuda:0" if args.device == "cuda" else "cpu"
    dtype = torch.float16 if args.device == "cuda" else torch.float32
    if args.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    raw_results = []
    intervals = []
    texts = []

    if args.candidate.startswith("qwen3"):
        from qwen_asr import Qwen3ASRModel

        model = Qwen3ASRModel.from_pretrained(
            model_path,
            dtype=dtype,
            device_map=device,
            attn_implementation="sdpa",
            max_inference_batch_size=1,
            max_new_tokens=args.max_new_tokens,
            forced_aligner=paths["aligner"],
            forced_aligner_kwargs={"dtype": dtype, "device_map": device,
                                   "attn_implementation": "sdpa"},
        )
        # SDK does not expose truncation status; reject token-limit termination
        # at the actual generation boundary instead of treating it as success.
        original_generate = model.model.generate

        def checked_generate(*positional: Any, **kwargs: Any) -> Any:
            result = original_generate(*positional, **kwargs)
            sequences = result.sequences if hasattr(result, "sequences") else result
            prompt_length = kwargs["input_ids"].shape[1]
            eos = model.model.generation_config.eos_token_id
            eos_ids = eos if isinstance(eos, list) else [eos]
            if sequences.shape[1] - prompt_length >= args.max_new_tokens:
                if any(int(row[-1]) not in eos_ids for row in sequences):
                    raise RuntimeError("ASR decoding reached token limit without EOS")
            return result

        model.model.generate = checked_generate
        loaded = time.monotonic()
        result = model.transcribe(audio=(audio, sample_rate), language="Chinese",
                                  return_time_stamps=True)[0]
        raw_results = [json_value(result)]
        texts = [result.text]
        if result.text.strip() and not result.time_stamps and not args.expect_silence:
            raise RuntimeError("Nonempty Qwen text without ForcedAligner timestamps")
        if result.time_stamps:
            intervals = [(v.start_time, v.end_time) for v in result.time_stamps.items]
        timestamp_source = "Qwen3-ForcedAligner-0.6B"
        timestamp_granularity = "character_or_word"
        from qwen_asr.inference.utils import MAX_FORCE_ALIGN_INPUT_SECONDS
        chunking = {"strategy": "official SDK", "max_seconds": MAX_FORCE_ALIGN_INPUT_SECONDS,
                    "overlap": 0}
    else:
        from funasr import AutoModel

        # Nano 1.3.0 is shipped in the wheel but not eagerly registered. Import
        # the reviewed, version-pinned packaged implementation, not remote code.
        if args.candidate == "fun-asr-nano":
            from funasr.models.fun_asr_nano.model import FunASRNano  # noqa: F401
        model = AutoModel(model=model_path, device=device, hub="hf",
                          disable_update=True, trust_remote_code=False)
        if args.candidate == "fun-asr-nano":
            original_generate = model.model.llm.generate

            def checked_nano_generate(*positional: Any, **kwargs: Any) -> Any:
                result = original_generate(*positional, **kwargs)
                eos = model.model.llm.generation_config.eos_token_id
                eos_ids = eos if isinstance(eos, list) else [eos]
                # With inputs_embeds, HF returns only the newly generated IDs.
                if result.shape[1] >= kwargs["max_new_tokens"]:
                    if any(int(row[-1]) not in eos_ids for row in result):
                        raise RuntimeError("Nano decoding reached token limit without EOS")
                return result

            model.model.llm.generate = checked_nano_generate
        loaded = time.monotonic()
        step = max(1, round(args.chunk_seconds * sample_rate))
        for begin in range(0, len(audio), step):
            end = min(len(audio), begin + step)
            pcm = torch.from_numpy(audio[begin:end])
            result = model.generate(input=pcm, cache={}, batch_size=1,
                                    language="zh", itn=True,
                                    max_length=args.max_new_tokens,
                                    llm_dtype=args.nano_dtype)[0]
            raw_results.append({"audio_start": begin / sample_rate,
                                "audio_end": end / sample_rate,
                                "result": json_value(result)})
            text = result.get("text", "")
            texts.append(text)
            if args.candidate == "paraformer-zh":
                timestamps = result.get("timestamp", [])
                if text.strip() and not timestamps and not args.expect_silence:
                    raise RuntimeError("Nonempty Paraformer text without timestamps")
                intervals.extend(((v[0] / 1000 + begin / sample_rate),
                                  (v[1] / 1000 + begin / sample_rate))
                                 for v in timestamps)
            elif text.strip():
                # This transcript consumed exactly this PCM slice. These are
                # actual audio boundaries, not invented sentence/word timing.
                intervals.append((begin / sample_rate, end / sample_rate))
        timestamp_source = "paraformer_native_ms" if args.candidate == "paraformer-zh" else "pcm_slice"
        timestamp_granularity = "character" if args.candidate == "paraformer-zh" else "audio_chunk"
        chunking = {"seconds": args.chunk_seconds, "overlap": 0}

    completed = time.monotonic()
    has_text = any(v.strip() for v in texts)
    if not args.expect_silence and (not has_text or not intervals):
        raise RuntimeError("Speech spike requires nonempty text and actual time intervals")
    verification = "failed_silence_hallucination" if args.expect_silence and has_text else "passed"
    check_intervals(intervals, duration)
    versions = {}
    for package in ["torch", "torchaudio", "transformers", "qwen-asr", "funasr", "numpy"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    payload = {
        "candidate": args.candidate, "verification": verification,
        "input_kind": "digital_silence" if args.expect_silence else "speech",
        "model_snapshot": model_path,
        "audio": str(args.audio.resolve()), "duration_seconds": duration,
        "device": args.device,
        "dtype": str(dtype) if args.candidate.startswith("qwen3") else (
            {"encoder": "float32", "decoder": args.nano_dtype}
            if args.candidate == "fun-asr-nano" else "float32"),
        "load_seconds": loaded - started, "inference_seconds": completed - loaded,
        "peak_torch_allocated_bytes": torch.cuda.max_memory_allocated() if args.device == "cuda" else None,
        "runtime_versions": versions, "timestamp_source": timestamp_source,
        "timestamp_granularity": timestamp_granularity, "chunking": chunking,
        "max_new_tokens": args.max_new_tokens,
        "full_text": "\n".join(texts), "intervals_seconds": intervals,
        "raw_results": raw_results,
        "warnings": ["Isolated spike, not pipeline integration or quality acceptance"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects evidence from accidental reruns.
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k: v for k, v in payload.items() if k not in {"raw_results", "intervals_seconds"}},
                     ensure_ascii=False, indent=2))
    return 0 if verification == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
