from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any

from src.asr.registry import Candidate
from src.asr.segmentation import aligned_segments, bounded_speech_intervals

PUNC_MODEL = "funasr/ct-punc"
PUNC_REVISION = "d0e55e2b8722a78b63705ff443d09c4f86e5d750"
PARAFORMER_WEIGHT_SHA256 = "3d491689244ec5dfbf9170ef3827c358aa10f1f20e42a7c59e15e688647946d1"


class FunasrBackend:
    def __init__(self, candidate: Candidate, device: str, cache: Path, parameters: dict[str, Any]):
        import torch
        from funasr import AutoModel
        from huggingface_hub import snapshot_download

        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用；不自动改用 CPU")
        self.candidate = candidate
        self.device = device
        self.limit = parameters.get("max_new_tokens", 2048)
        self.chunk_seconds = parameters.get("chunk_seconds", 30.0)
        self.decoder_dtype = "bf16" if device == "cuda" else "fp32"
        if candidate.id == "fun-asr-nano":
            if device == "cuda" and not torch.cuda.is_bf16_supported():
                raise ValueError("Nano 的已验证 CUDA 路径要求 BF16 支持；不静默切换精度")
            from funasr.models.fun_asr_nano.model import FunASRNano  # noqa: F401
            path = snapshot_download(candidate.model, revision=candidate.revision, cache_dir=str(cache / "hf"),
                                     allow_patterns=["*.json", "*.yaml", "*.txt", "model.pt", "multilingual.tiktoken"])
        else:
            from modelscope import snapshot_download as ms_download
            path = ms_download(candidate.model, revision=candidate.revision, cache_dir=str(cache / "ms"),
                               allow_patterns=["*.json", "*.yaml", "model.pt", "am.mvn", "seg_dict"])
        if candidate.id == "paraformer-zh":
            digest = hashlib.sha256()
            with (Path(path) / "model.pt").open("rb") as file:
                for block in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != PARAFORMER_WEIGHT_SHA256:
                raise ValueError("Paraformer checkpoint SHA256 与已验证 v2.0.4 不一致")
        self.model = AutoModel(model=path, device="cuda:0" if device == "cuda" else "cpu",
                               hub="hf", disable_update=True, trust_remote_code=False)
        self.punc = None
        if candidate.id == "paraformer-zh":
            punc_path = snapshot_download(PUNC_MODEL, revision=PUNC_REVISION, cache_dir=str(cache / "hf"),
                                          allow_patterns=["*.json", "*.yaml", "model.pt", "tokens.txt"])
            self.punc = AutoModel(model=punc_path, device="cpu", hub="hf", disable_update=True,
                                  trust_remote_code=False)
        else:
            original_generate = self.model.model.llm.generate

            def checked_generate(*args: Any, **kwargs: Any) -> Any:
                # The SDK sends a single unpadded sequence of audio/text embeds.
                embeds = kwargs["inputs_embeds"]
                kwargs.setdefault("attention_mask", torch.ones(embeds.shape[:2], dtype=torch.long, device=embeds.device))
                eos = self.model.model.llm.generation_config.eos_token_id
                eos_ids = eos if isinstance(eos, list) else [eos]
                kwargs.setdefault("pad_token_id", eos_ids[0])
                output = original_generate(*args, **kwargs)
                if output.shape[1] >= kwargs["max_new_tokens"]:
                    if any(int(row[-1]) not in eos_ids for row in output):
                        raise RuntimeError("Nano 解码达到 token 上限，拒绝发布截断转录")
                return output

            self.model.model.llm.generate = checked_generate

    def transcribe(self, audio: Any, sample_rate: int, duration: float, terms: list[str],
                   speech_regions: list[dict[str, int]]) -> tuple[list[dict], dict]:
        import torch

        step = max(1, round(self.chunk_seconds * sample_rate))
        segments = []
        intervals = []
        slices = bounded_speech_intervals(speech_regions, len(audio), step)
        for begin, finish in slices:
            pcm = torch.from_numpy(audio[begin:finish].copy())
            intervals.append([begin / sample_rate, finish / sample_rate])
            if not bool(torch.any(pcm)):
                continue
            kwargs = {"language": "zh", "itn": True, "max_length": self.limit}
            if self.candidate.id == "fun-asr-nano":
                kwargs.update(hotwords=terms, llm_dtype=self.decoder_dtype,
                              llm_kwargs={"do_sample": False, "repetition_penalty": 1.1})
            else:
                kwargs.update(hotword=" ".join(terms))
            try:
                raw = self.model.generate(input=pcm, cache={}, batch_size=1, **kwargs)[0]
            except Exception as exc:
                raise RuntimeError(f"{self.candidate.id} 分块 [{begin / sample_rate}, {finish / sample_rate}] 失败: {exc}") from exc
            text = raw.get("text", "").strip()
            if not text:
                raise ValueError(f"VAD 语音分块 [{begin / sample_rate}, {finish / sample_rate}] 返回空文字，拒绝静默遗漏")
            if self.candidate.id == "paraformer-zh":
                stamps = raw.get("timestamp", [])
                tokens = text.split()
                if len(tokens) != len(stamps) or not stamps:
                    raise ValueError("Paraformer 文字与字符/词时间戳数量不一致")
                # Punctuation restoration is separate; lexical mismatch fails closed.
                punctuated = self.punc.generate(input=text, cache={})[0]["text"]
                offset = begin / sample_rate
                units = [(token, start / 1000 + offset, end / 1000 + offset)
                         for token, (start, end) in zip(tokens, stamps)]
                current = aligned_segments(punctuated, units, duration)
            else:
                current = [{"start": begin / sample_rate, "end": finish / sample_rate, "text": text}]
            for item in current:
                item["id"] = len(segments) + 1
                segments.append(item)
        return segments, {
            "timestamp_source": "paraformer_native_ms" if self.punc else "silero_vad_pcm_slice",
            "timestamp_granularity": "text_segment_from_character_or_word_alignment" if self.punc else "vad_audio_chunk",
            "resolved_parameters": {"batch_size": 1, "max_new_tokens": self.limit,
                                    "encoder_dtype": "float32", "decoder_dtype": self.decoder_dtype if not self.punc else "float32",
                                    "hotwords": terms, "do_sample": False if not self.punc else None,
                                    "repetition_penalty": 1.1 if not self.punc else None},
            "punctuation_model": {"model": PUNC_MODEL, "revision": PUNC_REVISION} if self.punc else None,
            "checkpoint_sha256": PARAFORMER_WEIGHT_SHA256 if self.punc else None,
            "chunking": {"strategy": "bounded Silero VAD PCM slices", "max_seconds": self.chunk_seconds,
                         "overlap": 0, "intervals": intervals},
            "warnings": (["长 VAD 语音区间按真实 PCM 上限切分；分块边界可能截断词语，需人工复核"]
                         if any(r["end"] - r["start"] > step for r in speech_regions) else []),
        }
