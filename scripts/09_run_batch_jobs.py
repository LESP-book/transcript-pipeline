from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import ConfigLoadError, load_settings
from src.job_runner import JobRunnerError, get_batch_exit_code, load_batch_job_specs, run_batch_jobs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按批量 job 输入契约运行完整主链。")
    parser.add_argument("--manifest", help="批量任务清单，支持 yaml/json")
    parser.add_argument("--videos-dir", help="视频目录")
    parser.add_argument("--reference-dir", help="参考原文目录，按 basename 配对")
    parser.add_argument("--shared-reference", help="共享参考源，本地 txt/md/pdf 或网页链接")
    parser.add_argument("--output-dir", help="最终 Markdown 输出目录")
    parser.add_argument("--config", help="配置文件路径，默认使用 config/settings.yaml")
    parser.add_argument("--profile", help="运行 profile，覆盖配置文件中的默认 profile")
    parser.add_argument("--glossary-file", help="批量默认术语词表文件，一行一个词条")
    parser.add_argument("--remote-concurrency", type=int, default=2, help="远程阶段并发度，默认 2")
    parser.add_argument("--book-name", help="批量默认书名，用于输出文件命名")
    parser.add_argument("--chapter", help="批量默认章节名，用于输出文件命名")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.remote_concurrency < 1:
        print("[ERROR] remote_concurrency 必须大于等于 1", file=sys.stderr)
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

    try:
        job_specs, failed_runtimes = load_batch_job_specs(
            base_loaded_settings=loaded_settings,
            manifest=args.manifest,
            videos_dir=args.videos_dir,
            reference_dir=args.reference_dir,
            shared_reference=args.shared_reference,
            output_dir=args.output_dir,
            book_name=args.book_name,
            chapter=args.chapter,
            glossary_file=args.glossary_file,
        )
        summary = run_batch_jobs(
            project_root=PROJECT_ROOT,
            base_loaded_settings=loaded_settings,
            job_specs=job_specs,
            failed_runtimes=failed_runtimes,
            remote_concurrency=args.remote_concurrency,
        )
    except JobRunnerError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    batch_root = PROJECT_ROOT / "data/jobs/batches" / summary.batch_id
    print(f"[OK] batch={summary.batch_id}")
    print(f"[OK] total={summary.total} success={summary.success} failed={summary.failed}")
    print(f"[OK] summary_json={batch_root / 'summary.json'}")
    return get_batch_exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
