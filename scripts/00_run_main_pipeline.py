from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_pipeline import run_stage
from src.config_loader import ConfigLoadError, load_settings
from src.runtime_utils import normalize_stage_name, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按当前推荐主链顺序运行完整流水线。")
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
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

    logger = setup_logging(loaded_settings.settings.runtime.log_level)
    pipeline_settings = loaded_settings.settings.pipeline
    raw_stages = pipeline_settings.stages if pipeline_settings is not None else []
    if not raw_stages:
        logger.error("当前配置未定义主链阶段列表。")
        return 1

    stages = [normalize_stage_name(stage_name) for stage_name in raw_stages]
    logger.info("主链启动 | profile=%s | stages=%s", loaded_settings.active_profile_name, ",".join(stages))

    for stage_name in stages:
        logger.info("主链执行 | stage=%s", stage_name)
        exit_code = run_stage(stage_name, loaded_settings, logger)
        if exit_code != 0:
            logger.error("主链失败 | stage=%s | exit_code=%s", stage_name, exit_code)
            return exit_code

    logger.info("主链完成 | stages=%s", ",".join(stages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
