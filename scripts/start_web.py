from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Callable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173


class StartWebError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同时启动 transcript-pipeline 后端 API 和前端 Web UI。")
    parser.add_argument("--host", default=DEFAULT_HOST, help="前后端监听地址，默认 127.0.0.1。")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT, help="后端 API 端口，默认 8000。")
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT, help="前端 Web UI 端口，默认 5173。")
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="启动进程后自动打开前端页面。",
    )
    return parser


def build_backend_command(venv_python: Path, host: str, port: int) -> list[str]:
    return [
        str(venv_python),
        "-m",
        "uvicorn",
        "api_server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]


def build_frontend_command(npm_path: str, host: str, port: int) -> list[str]:
    return [
        npm_path,
        "run",
        "dev",
        "--",
        "--host",
        host,
        "--port",
        str(port),
        "--strictPort",
    ]


def build_frontend_env(base_env: Mapping[str, str], host: str, backend_port: int) -> dict[str, str]:
    env = dict(base_env)
    env["TRANSCRIPT_API_PROXY_TARGET"] = f"http://{host}:{backend_port}"
    return env


def check_prerequisites(project_root: Path) -> tuple[Path, str]:
    venv_python = project_root / ".venv/bin/python"
    if not venv_python.exists():
        raise StartWebError("未找到项目内 .venv/bin/python，请先初始化 Python 虚拟环境。")

    frontend_dir = project_root / "frontend"
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        raise StartWebError("未找到 frontend/package.json，无法启动前端。")

    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        raise StartWebError('未找到 frontend/node_modules，请先执行：cd "frontend" && npm install')

    npm_path = shutil.which("npm")
    if npm_path is None:
        raise StartWebError("未找到 npm 命令，请先安装 Node.js / npm。")

    return venv_python, npm_path


def start_process(
    *,
    name: str,
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> subprocess.Popen:
    print(f"[{name}] 启动命令：{' '.join(command)}")
    return popen_factory(
        list(command),
        cwd=str(cwd),
        env=dict(env) if env is not None else None,
        start_new_session=os.name != "nt",
    )


def stop_process(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    print(f"[{name}] 正在停止...")
    if os.name != "nt":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    process.wait()


def wait_for_exit(processes: Mapping[str, subprocess.Popen]) -> tuple[str, int]:
    while True:
        for name, process in processes.items():
            return_code = process.poll()
            if return_code is not None:
                return name, return_code
        time.sleep(0.2)


def run(args: argparse.Namespace) -> int:
    venv_python, npm_path = check_prerequisites(PROJECT_ROOT)
    backend_url = f"http://{args.host}:{args.backend_port}"
    frontend_url = f"http://{args.host}:{args.frontend_port}"
    processes: dict[str, subprocess.Popen] = {}

    try:
        processes["后端"] = start_process(
            name="后端",
            command=build_backend_command(venv_python, args.host, args.backend_port),
            cwd=PROJECT_ROOT,
        )
        processes["前端"] = start_process(
            name="前端",
            command=build_frontend_command(npm_path, args.host, args.frontend_port),
            cwd=PROJECT_ROOT / "frontend",
            env=build_frontend_env(os.environ, args.host, args.backend_port),
        )

        print("")
        print(f"后端 API：{backend_url}")
        print(f"前端页面：{frontend_url}")
        print("按 Ctrl+C 可同时停止前端和后端。")
        if args.open_browser:
            webbrowser.open(frontend_url)

        stopped_name, return_code = wait_for_exit(processes)
        print(f"[{stopped_name}] 已退出，返回码：{return_code}")
        return return_code
    except KeyboardInterrupt:
        print("\n收到停止请求，正在关闭前端和后端...")
        return 0
    except OSError as exc:
        raise StartWebError(f"启动进程失败：{exc}") from exc
    finally:
        for name, process in reversed(processes.items()):
            stop_process(name, process)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except StartWebError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
