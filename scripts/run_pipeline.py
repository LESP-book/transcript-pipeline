from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import ConfigLoadError, load_settings
from src.align_utils import AlignmentError, align_batch, summarize_alignment_results
from src.asr_utils import AsrTranscriptionError, summarize_transcription_results, transcribe_batch
from src.classify_utils import ClassificationError, classify_batch, summarize_classification_results
from src.export_utils import ExportError, export_markdown_batch, summarize_export_results
from src.ffmpeg_utils import AudioExtractionError, extract_audio_batch, summarize_extraction_results
from src.refine_utils import RefinementError, refine_batch, summarize_refinement_results
from src.reference_utils import (
    ReferencePreparationError,
    prepare_reference_batch,
    summarize_reference_results,
)
from src.runtime_utils import normalize_stage_name, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行最小流水线入口。")
    parser.add_argument(
        "--stage",
        required=True,
        help="当前支持 extract-audio、transcribe、prepare-reference、align、classify、refine 或 export-markdown",
    )
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
    return parser


def run_stage(stage_name: str, loaded_settings, logger) -> int:
    if stage_name == "extract-audio":
        try:
            results = extract_audio_batch(loaded_settings, logger=logger)
        except AudioExtractionError as exc:
            logger.error("%s", exc)
            return 1

        logger.info("流水线完成 | stage=%s | %s", stage_name, summarize_extraction_results(results))
        return 0

    if stage_name == "transcribe":
        try:
            outputs = transcribe_batch(loaded_settings, logger=logger)
        except AsrTranscriptionError as exc:
            logger.error("%s", exc)
            return 1

        logger.info("流水线完成 | stage=%s | %s", stage_name, summarize_transcription_results(outputs))
        return 0

    if stage_name == "prepare-reference":
        try:
            summary = prepare_reference_batch(loaded_settings, logger=logger)
        except ReferencePreparationError as exc:
            logger.error("%s", exc)
            return 1

        logger.info("流水线完成 | stage=%s | %s", stage_name, summarize_reference_results(summary))
        return 0

    if stage_name == "align":
        try:
            summary = align_batch(loaded_settings, logger=logger)
        except AlignmentError as exc:
            logger.error("%s", exc)
            return 1

        logger.info("流水线完成 | stage=%s | %s", stage_name, summarize_alignment_results(summary))
        return 0

    if stage_name == "classify":
        try:
            summary = classify_batch(loaded_settings, logger=logger)
        except ClassificationError as exc:
            logger.error("%s", exc)
            return 1

        logger.info("流水线完成 | stage=%s | %s", stage_name, summarize_classification_results(summary))
        return 0

    if stage_name == "refine":
        try:
            summary = refine_batch(loaded_settings, logger=logger)
        except RefinementError as exc:
            logger.error("%s", exc)
            return 1

        logger.info("流水线完成 | stage=%s | %s", stage_name, summarize_refinement_results(summary))
        return 0

    if stage_name == "export-markdown":
        try:
            summary = export_markdown_batch(loaded_settings, logger=logger)
        except ExportError as exc:
            logger.error("%s", exc)
            return 1

        logger.info("流水线完成 | stage=%s | %s", stage_name, summarize_export_results(summary))
        return 0

    logger.error("未实现的阶段: %s", stage_name)
    return 1


def main() -> int:
    args = build_parser().parse_args()

    try:
        stage_name = normalize_stage_name(args.stage)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

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
    logger.info("流水线启动 | stage=%s | profile=%s", stage_name, loaded_settings.active_profile_name)
    return run_stage(stage_name, loaded_settings, logger)


if __name__ == "__main__":
    raise SystemExit(main())
