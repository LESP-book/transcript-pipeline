from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config_loader import ConfigLoadError, load_settings
from src.ffmpeg_utils import AudioExtractionError
from src.pipeline_jobs import run_local_preprocess_job
from src.runtime_utils import setup_logging
from src.asr_utils import AsrTranscriptionError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行本地前处理主链：抽音频 + ASR。")
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
    parser.add_argument("--quality-tier", help="ASR 质量档位，默认使用配置文件中的 asr.quality_tier")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        loaded_settings = load_settings(
            settings_path=args.config,
            profile_name=args.profile,
            project_root=PROJECT_ROOT,
        )
    except ConfigLoadError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    logger = setup_logging(loaded_settings.settings.runtime.log_level)
    try:
        result = run_local_preprocess_job(
            loaded_settings,
            logger=logger,
            quality_tier_name=args.quality_tier,
        )
    except (AudioExtractionError, AsrTranscriptionError) as exc:
        logger.error("%s", exc)
        return 1

    print(
        "[OK] "
        f"quality_tier={result.quality_tier_name} "
        f"audio={len(result.extracted_audio)} "
        f"asr={len(result.transcribed_audio)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
