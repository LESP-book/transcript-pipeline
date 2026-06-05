from __future__ import annotations

import argparse
import ipaddress
import os
import shutil
import signal
import socket
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
WSL_OS_RELEASE_PATH = Path("/proc/sys/kernel/osrelease")


class StartWebError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同时启动 transcript-pipeline 后端 API 和前端 Web UI。")
    parser.add_argument("--host", default=DEFAULT_HOST, help="前后端监听地址，默认 127.0.0.1。")
    parser.add_argument("--lan", action="store_true", help="监听 0.0.0.0，允许同一局域网内其他设备访问。")
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


def resolve_bind_host(host: str, lan: bool) -> str:
    if lan and host == DEFAULT_HOST:
        return "0.0.0.0"
    return host


def proxy_target_host(bind_host: str) -> str:
    if bind_host == "0.0.0.0":
        return "127.0.0.1"
    if bind_host == "::":
        return "[::1]"
    return bind_host


def build_frontend_env(base_env: Mapping[str, str], host: str, backend_port: int) -> dict[str, str]:
    env = dict(base_env)
    env["TRANSCRIPT_API_PROXY_TARGET"] = f"http://{proxy_target_host(host)}:{backend_port}"
    return env


def local_display_host(bind_host: str) -> str:
    if bind_host == "0.0.0.0":
        return "127.0.0.1"
    if bind_host == "::":
        return "[::1]"
    return bind_host


def discover_lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for address in socket.gethostbyname_ex(hostname)[2]:
            if not address.startswith("127.") and address != "0.0.0.0":
                addresses.add(address)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.connect(("8.8.8.8", 80))
            address = udp_socket.getsockname()[0]
            if not address.startswith("127.") and address != "0.0.0.0":
                addresses.add(address)
    except OSError:
        pass

    return sorted(addresses)


def build_share_urls(bind_host: str, port: int) -> list[str]:
    if bind_host == "0.0.0.0":
        return [f"http://{address}:{port}" for address in discover_lan_addresses()]
    if bind_host == "::":
        return []
    return [f"http://{bind_host}:{port}"]


def parse_ipv4_addresses(text: str) -> list[str]:
    addresses: list[str] = []
    for item in text.replace("\r", "\n").split():
        try:
            address = ipaddress.ip_address(item)
        except ValueError:
            continue
        if address.version != 4 or address.is_loopback or address.is_unspecified:
            continue
        addresses.append(str(address))
    return sorted(dict.fromkeys(addresses))


def read_kernel_release(path: Path = WSL_OS_RELEASE_PATH) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def is_wsl_environment(
    *,
    environ: Mapping[str, str] | None = None,
    kernel_release: str | None = None,
) -> bool:
    env = os.environ if environ is None else environ
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    release = read_kernel_release() if kernel_release is None else kernel_release
    return "microsoft" in release.lower() or "wsl" in release.lower()


def discover_wsl_ipv4_addresses() -> list[str]:
    addresses: list[str] = []
    eth0_address = discover_interface_ipv4_address("eth0")
    if eth0_address:
        addresses.append(eth0_address)
    primary_address = discover_primary_ipv4_address()
    if primary_address:
        addresses.append(primary_address)
    try:
        output = subprocess.check_output(["hostname", "-I"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return addresses
    addresses.extend(parse_ipv4_addresses(output))
    return list(dict.fromkeys(addresses))


def discover_interface_ipv4_address(interface_name: str) -> str | None:
    try:
        output = subprocess.check_output(
            ["ip", "-4", "addr", "show", "dev", interface_name],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("inet "):
            continue
        address_with_prefix = stripped.split()[1]
        addresses = parse_ipv4_addresses(address_with_prefix.split("/", 1)[0])
        if addresses:
            return addresses[0]
    return None


def discover_primary_ipv4_address() -> str | None:
    try:
        output = subprocess.check_output(["ip", "-4", "route", "get", "1.1.1.1"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = output.split()
    if "src" not in parts:
        return None
    source_index = parts.index("src") + 1
    if source_index >= len(parts):
        return None
    addresses = parse_ipv4_addresses(parts[source_index])
    if not addresses:
        return None
    return addresses[0]


def discover_windows_lan_addresses() -> list[str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        (
            "Get-NetIPAddress -AddressFamily IPv4 | "
            "Where-Object { "
            "$_.IPAddress -notlike '127.*' -and "
            "$_.IPAddress -notlike '169.254.*' -and "
            "$_.IPAddress -notlike '172.16.*' -and "
            "$_.IPAddress -notlike '172.17.*' -and "
            "$_.IPAddress -notlike '172.18.*' -and "
            "$_.IPAddress -notlike '172.19.*' -and "
            "$_.InterfaceAlias -notmatch 'vEthernet|WSL|Docker|Loopback' "
            "} | Select-Object -ExpandProperty IPAddress"
        ),
    ]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_ipv4_addresses(output)


def build_wsl_portproxy_commands(wsl_address: str, frontend_port: int) -> list[str]:
    return [
        (
            "netsh interface portproxy add v4tov4 "
            f"listenaddress=0.0.0.0 listenport={frontend_port} "
            f"connectaddress={wsl_address} connectport={frontend_port}"
        ),
        (
            'netsh advfirewall firewall add rule name="Transcript Pipeline Web '
            f'{frontend_port}" dir=in action=allow protocol=TCP localport={frontend_port}'
        ),
    ]


def print_wsl_lan_guidance(frontend_port: int) -> None:
    wsl_addresses = discover_wsl_ipv4_addresses()
    windows_addresses = discover_windows_lan_addresses()
    wsl_address = wsl_addresses[0] if wsl_addresses else "<WSL_IP>"

    print("")
    print("WSL 局域网访问提示：")
    print("- 当前进程运行在 WSL 中。WSL2 默认 NAT 模式下，其他电脑通常不能直接访问 WSL 内部地址。")
    print("- Windows 主机本机可先访问：http://127.0.0.1:%s" % frontend_port)
    if windows_addresses:
        print("- 配置端口转发后，局域网其他电脑访问 Windows 主机地址：")
        for address in windows_addresses:
            print(f"  - http://{address}:{frontend_port}")
    else:
        print("- 配置端口转发后，局域网其他电脑访问：http://<Windows主机局域网IP>:%s" % frontend_port)
    if wsl_addresses:
        print("- 当前 WSL 地址用于 Windows 端口转发：%s" % ", ".join(wsl_addresses))
    else:
        print("- 未能自动识别 WSL 地址，可在 WSL 内执行 `hostname -I` 后填入 <WSL_IP>。")
    print("- 请在 Windows 管理员 PowerShell 执行以下命令：")
    for command in build_wsl_portproxy_commands(wsl_address, frontend_port):
        print(f"  {command}")
    print("- WSL 重启后内部 IP 可能变化；如果访问失效，请重新执行上面的 portproxy 命令。")
    print("- 如果已启用 WSL mirrored networking，通常只需要确认 Windows / Hyper-V 防火墙允许端口 %s。" % frontend_port)


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
    bind_host = resolve_bind_host(args.host, args.lan)
    display_host = local_display_host(bind_host)
    backend_url = f"http://{display_host}:{args.backend_port}"
    frontend_url = f"http://{display_host}:{args.frontend_port}"
    processes: dict[str, subprocess.Popen] = {}

    try:
        processes["后端"] = start_process(
            name="后端",
            command=build_backend_command(venv_python, bind_host, args.backend_port),
            cwd=PROJECT_ROOT,
        )
        processes["前端"] = start_process(
            name="前端",
            command=build_frontend_command(npm_path, bind_host, args.frontend_port),
            cwd=PROJECT_ROOT / "frontend",
            env=build_frontend_env(os.environ, bind_host, args.backend_port),
        )

        print("")
        print(f"后端 API：{backend_url}")
        print(f"前端页面：{frontend_url}")
        share_urls = build_share_urls(bind_host, args.frontend_port)
        if args.lan or bind_host in {"0.0.0.0", "::"}:
            wsl_environment = is_wsl_environment()
            if share_urls and wsl_environment:
                print("WSL 内部监听地址（局域网其他电脑不一定能直接访问）：")
                for url in share_urls:
                    print(f"- {url}")
            elif share_urls:
                print("局域网分享地址：")
                for url in share_urls:
                    print(f"- {url}")
            else:
                print("局域网分享地址：未自动识别到局域网 IP，请使用本机固定 IP 拼接前端端口访问。")
            if wsl_environment:
                print_wsl_lan_guidance(args.frontend_port)
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
