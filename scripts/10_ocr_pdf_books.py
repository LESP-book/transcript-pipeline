from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import ConfigLoadError, load_settings
from src.pdf_book_ocr import PDFBookOCRError, ocr_pdf_book_batch, summarize_pdf_book_ocr
from src.runtime_utils import setup_logging
from src.settings_overrides import ModelOverrides, SettingsOverrideError, apply_model_overrides


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="独立识别 PDF 书籍，输出每本书对应的纯文本 TXT。")
    parser.add_argument("input_path", help="单个 PDF 文件，或包含 PDF 书籍的文件夹")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "output" / "pdf" / "ocr"),
        help="TXT 输出目录；批量输入时会保留原目录层级",
    )
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
    parser.add_argument("--ocr-model", help="覆盖 Codex API OCR 使用的模型，例如 gpt-5.6-terra")
    parser.add_argument("--ocr-reasoning-effort", help="覆盖 Codex API OCR reasoning effort，例如 low / medium / high")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        loaded_settings = load_settings(
            settings_path=args.config,
            profile_name=args.profile,
            project_root=PROJECT_ROOT,
        )
        apply_model_overrides(
            loaded_settings,
            ModelOverrides(ocr_model=args.ocr_model, ocr_reasoning_effort=args.ocr_reasoning_effort),
        )
    except (ConfigLoadError, SettingsOverrideError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    logger = setup_logging(loaded_settings.settings.runtime.log_level)
    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    logger.info(
        "PDF 书籍 OCR 启动 | input=%s | output=%s | profile=%s",
        input_path,
        output_dir,
        loaded_settings.active_profile_name,
    )

    try:
        summary = ocr_pdf_book_batch(input_path, output_dir, loaded_settings)
    except PDFBookOCRError as exc:
        logger.error("%s", exc)
        return 1

    for item in summary.items:
        if item.success:
            logger.info(
                "PDF OCR 成功 | source=%s | output=%s | text_length=%s",
                item.source_pdf,
                item.output_text_path,
                item.text_length,
            )
        else:
            logger.error("PDF OCR 失败 | source=%s | error=%s", item.source_pdf, item.error)

    logger.info("PDF 书籍 OCR 完成 | %s", summarize_pdf_book_ocr(summary))
    return 0 if summary.failure_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
