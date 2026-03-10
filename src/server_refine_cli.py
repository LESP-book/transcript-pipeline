from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config_loader import ConfigLoadError, load_settings
from src.job_runner import JobRunnerError, run_server_refine_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="基于现成 ASR 工件执行服务端精修主链。")
    parser.add_argument("--asr-json", required=True, help="ASR JSON 文件路径")
    parser.add_argument("--asr-text", required=True, help="ASR TXT 文件路径")
    parser.add_argument("--reference", required=True, help="参考源：本地 txt/md/pdf 或网页链接")
    parser.add_argument("--output-dir", required=True, help="最终 Markdown 输出目录")
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
    parser.add_argument("--book-name", help="可选书名，用于输出文件命名")
    parser.add_argument("--chapter", help="可选章节名，用于输出文件命名")
    parser.add_argument("--glossary-file", help="可选附加术语词表文件，一行一个词条")
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

    try:
        result = run_server_refine_job(
            project_root=loaded_settings.project_root,
            base_loaded_settings=loaded_settings,
            asr_json=args.asr_json,
            asr_text=args.asr_text,
            reference=args.reference,
            output_dir=args.output_dir,
            profile=args.profile,
            book_name=args.book_name,
            chapter=args.chapter,
            glossary_file=args.glossary_file,
        )
    except JobRunnerError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] job={result.job_id}")
    print(f"[OK] job_dir={result.job_root}")
    print(f"[OK] final_markdown={result.copied_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
