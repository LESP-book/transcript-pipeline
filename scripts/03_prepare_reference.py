from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import ConfigLoadError, load_settings
from src.reference_utils import (
    ReferencePreparationError,
    prepare_reference_batch,
    summarize_reference_results,
)
from src.runtime_utils import setup_logging
from src.settings_overrides import ModelOverrides, SettingsOverrideError, apply_model_overrides


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="准备参考原文，统一提取为纯文本。")
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
    parser.add_argument("--ocr-model", help="覆盖 Codex API OCR 使用的模型，例如 gpt-5.4-mini")
    parser.add_argument("--ocr-reasoning-effort", help="覆盖 Codex API OCR reasoning effort，例如 low / medium / high")
    parser.add_argument("--ocr-max-concurrency", type=int, help="覆盖 PDF OCR 最大在途请求数，默认读取配置（当前默认 40）")
    parser.add_argument("--ocr-submit-interval-seconds", type=float, help="覆盖 PDF OCR 页面投递间隔秒数，默认读取配置（当前默认 5）")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        loaded_settings = load_settings(
            settings_path=args.config,
            profile_name=args.profile,
            project_root=PROJECT_ROOT,
        )
    except ConfigLoadError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    try:
        apply_model_overrides(
            loaded_settings,
            ModelOverrides(
                ocr_model=args.ocr_model,
                ocr_reasoning_effort=args.ocr_reasoning_effort,
                ocr_max_concurrency=args.ocr_max_concurrency,
                ocr_submit_interval_seconds=args.ocr_submit_interval_seconds,
            ),
        )
    except SettingsOverrideError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    logger = setup_logging(loaded_settings.settings.runtime.log_level)
    logger.info("阶段启动 | prepare-reference | profile=%s", loaded_settings.active_profile_name)

    try:
        summary = prepare_reference_batch(loaded_settings, logger=logger)
    except ReferencePreparationError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("阶段完成 | prepare-reference | %s", summarize_reference_results(summary))
    if summary.partial:
        return 2
    if summary.failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
