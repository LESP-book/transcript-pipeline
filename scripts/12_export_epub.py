from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.epub_export import EpubExportError, export_epub


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把整合后的 OCR TXT 导出为 EPUB 3。")
    parser.add_argument("input_text", help="已经整合完成的 UTF-8 TXT")
    parser.add_argument("--output", help="EPUB 输出路径，默认使用输入 TXT 的同名 .epub")
    parser.add_argument("--title", help="EPUB 书名，默认使用输入文件名")
    parser.add_argument("--author", help="EPUB 作者")
    parser.add_argument("--language", default="zh-CN", help="书籍语言，默认 zh-CN")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = export_epub(
            Path(args.input_text),
            Path(args.output) if args.output else None,
            title=args.title,
            author=args.author,
            language=args.language,
        )
    except EpubExportError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    document = result.document
    print(
        f"[INFO] EPUB 导出完成 | output={result.output_path} "
        f"| blocks={len(document.body_blocks)} "
        f"| footnotes={len(document.footnotes)} "
        f"| endnotes={len(document.endnotes)} "
        f"| references={len(document.references)} "
        f"| warnings={len(document.warnings)}"
    )
    for warning in document.warnings:
        print(f"[WARNING] {warning.format()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
