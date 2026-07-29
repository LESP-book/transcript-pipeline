from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.text_integration import (
    TextIntegrationError,
    build_default_integrated_output_path,
    integrate_ocr_texts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按稳定顺序整合 OCR TXT 片段，生成独立的 UTF-8 TXT。")
    parser.add_argument("input_path", help="单个 OCR TXT，或只包含同一本书片段的文件夹")
    parser.add_argument("--output", help="整合 TXT 输出路径；默认生成不覆盖输入的 .integrated.txt")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input_path)
    output_path = Path(args.output) if args.output else build_default_integrated_output_path(input_path)

    try:
        result = integrate_ocr_texts(input_path, output_path)
    except TextIntegrationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(
        f"[INFO] OCR TXT 整合完成 | sources={len(result.source_paths)} "
        f"| characters={result.character_count} | output={result.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
