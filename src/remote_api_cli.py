from __future__ import annotations

import argparse
import os

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动远程协调 API 服务。")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式自动重载")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--profile", help="运行 profile")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    previous_settings_path = os.environ.get("TRANSCRIPT_SETTINGS_PATH")
    previous_profile = os.environ.get("TRANSCRIPT_PROFILE")
    try:
        if args.config:
            os.environ["TRANSCRIPT_SETTINGS_PATH"] = args.config
        elif "TRANSCRIPT_SETTINGS_PATH" in os.environ:
            os.environ.pop("TRANSCRIPT_SETTINGS_PATH")
        if args.profile:
            os.environ["TRANSCRIPT_PROFILE"] = args.profile
        elif "TRANSCRIPT_PROFILE" in os.environ:
            os.environ.pop("TRANSCRIPT_PROFILE")

        uvicorn.run(
            "src.remote_api:create_default_app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            factory=True,
        )
    finally:
        if previous_settings_path is None:
            os.environ.pop("TRANSCRIPT_SETTINGS_PATH", None)
        else:
            os.environ["TRANSCRIPT_SETTINGS_PATH"] = previous_settings_path

        if previous_profile is None:
            os.environ.pop("TRANSCRIPT_PROFILE", None)
        else:
            os.environ["TRANSCRIPT_PROFILE"] = previous_profile
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
