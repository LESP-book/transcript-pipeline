from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import ConfigLoadError, load_settings
from src.job_runner import JobRunnerError, run_single_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按单任务输入绑定方式运行完整主链。")
    parser.add_argument("--video", required=True, help="输入视频文件路径")
    parser.add_argument("--reference", required=True, help="参考源：本地 txt/md/pdf 或网页链接")
    parser.add_argument("--output-dir", required=True, help="最终 Markdown 输出目录")
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
    parser.add_argument("--book-name", help="可选书名，用于输出文件命名")
    parser.add_argument("--chapter", help="可选章节名，用于输出文件命名")
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
        result = run_single_job(
            project_root=PROJECT_ROOT,
            base_loaded_settings=loaded_settings,
            video=args.video,
            reference=args.reference,
            output_dir=args.output_dir,
            profile=args.profile,
            book_name=args.book_name,
            chapter=args.chapter,
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
