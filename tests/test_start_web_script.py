from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def load_start_web_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts/start_web.py"
    spec = importlib.util.spec_from_file_location("start_web_script", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_commands_use_project_venv_and_configured_ports() -> None:
    module = load_start_web_module()

    backend_command = module.build_backend_command(Path(".venv/bin/python"), "127.0.0.1", 8100)
    frontend_command = module.build_frontend_command("/usr/bin/npm", "127.0.0.1", 5200)

    assert backend_command == [
        ".venv/bin/python",
        "-m",
        "uvicorn",
        "api_server:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8100",
    ]
    assert frontend_command == [
        "/usr/bin/npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5200",
        "--strictPort",
    ]


def test_frontend_env_points_proxy_to_backend_port() -> None:
    module = load_start_web_module()

    env = module.build_frontend_env({"KEEP": "yes"}, "127.0.0.1", 8100)

    assert env["KEEP"] == "yes"
    assert env["TRANSCRIPT_API_PROXY_TARGET"] == "http://127.0.0.1:8100"


def test_frontend_env_uses_loopback_proxy_when_binding_all_interfaces() -> None:
    module = load_start_web_module()

    env = module.build_frontend_env({}, "0.0.0.0", 8100)

    assert env["TRANSCRIPT_API_PROXY_TARGET"] == "http://127.0.0.1:8100"


def test_lan_flag_binds_all_interfaces_only_for_default_host() -> None:
    module = load_start_web_module()

    assert module.resolve_bind_host("127.0.0.1", True) == "0.0.0.0"
    assert module.resolve_bind_host("192.168.1.10", True) == "192.168.1.10"
    assert module.resolve_bind_host("127.0.0.1", False) == "127.0.0.1"


def test_parse_ipv4_addresses_filters_loopback_and_invalid_items() -> None:
    module = load_start_web_module()

    assert module.parse_ipv4_addresses("127.0.0.1 172.30.98.229 invalid 0.0.0.0 192.168.1.20") == [
        "172.30.98.229",
        "192.168.1.20",
    ]


def test_is_wsl_environment_detects_env_and_kernel_release() -> None:
    module = load_start_web_module()

    assert module.is_wsl_environment(environ={"WSL_DISTRO_NAME": "Debian"}, kernel_release="linux") is True
    assert module.is_wsl_environment(environ={}, kernel_release="5.15.167.4-microsoft-standard-WSL2") is True
    assert module.is_wsl_environment(environ={}, kernel_release="6.8.0-generic") is False


def test_build_wsl_portproxy_commands_points_windows_port_to_wsl_address() -> None:
    module = load_start_web_module()

    commands = module.build_wsl_portproxy_commands("172.30.98.229", 5173)

    assert commands == [
        (
            "netsh interface portproxy add v4tov4 "
            "listenaddress=0.0.0.0 listenport=5173 "
            "connectaddress=172.30.98.229 connectport=5173"
        ),
        (
            'netsh advfirewall firewall add rule name="Transcript Pipeline Web '
            '5173" dir=in action=allow protocol=TCP localport=5173'
        ),
    ]


def test_discover_wsl_ipv4_addresses_prefers_eth0_before_route_and_hostname(monkeypatch) -> None:
    module = load_start_web_module()

    def fake_check_output(command, **_kwargs):
        if command == ["ip", "-4", "addr", "show", "dev", "eth0"]:
            return "2: eth0:\n    inet 172.30.98.229/20 brd 172.30.111.255 scope global eth0"
        if command[:4] == ["ip", "-4", "route", "get"]:
            return "1.1.1.1 via 172.18.0.2 dev docker0 src 172.18.0.1 uid 1000"
        if command == ["hostname", "-I"]:
            return "172.17.0.1 172.30.98.229 172.18.0.1"
        raise AssertionError(f"不应执行的命令: {command}")

    monkeypatch.setattr(module.subprocess, "check_output", fake_check_output)

    assert module.discover_wsl_ipv4_addresses() == ["172.30.98.229", "172.18.0.1", "172.17.0.1"]


def test_check_prerequisites_requires_project_venv(tmp_path: Path) -> None:
    module = load_start_web_module()

    try:
        module.check_prerequisites(tmp_path)
    except module.StartWebError as exc:
        assert ".venv/bin/python" in str(exc)
    else:
        raise AssertionError("缺少 .venv 时应明确失败")


def test_run_starts_backend_and_frontend_then_stops_peer(monkeypatch) -> None:
    module = load_start_web_module()
    seen: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self, pid: int, return_code: int | None = None) -> None:
            self.pid = pid
            self.return_code = return_code
            self.wait_called = False

        def poll(self) -> int | None:
            return self.return_code

        def wait(self) -> int:
            self.wait_called = True
            self.return_code = 0
            return 0

    backend = FakeProcess(101, return_code=3)
    frontend = FakeProcess(102)

    def fake_start_process(**kwargs):
        seen.append(kwargs)
        if kwargs["name"] == "后端":
            return backend
        return frontend

    monkeypatch.setattr(module, "check_prerequisites", lambda _root: (Path(".venv/bin/python"), "/usr/bin/npm"))
    monkeypatch.setattr(module, "start_process", fake_start_process)
    monkeypatch.setattr(module.os, "killpg", lambda _pid, _signal: None)

    args = SimpleNamespace(host="127.0.0.1", lan=False, backend_port=8000, frontend_port=5173, open_browser=False)

    assert module.run(args) == 3
    assert [item["name"] for item in seen] == ["后端", "前端"]
    assert frontend.wait_called is True


def test_run_lan_mode_starts_processes_on_all_interfaces(monkeypatch) -> None:
    module = load_start_web_module()
    seen: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self, pid: int, return_code: int | None = None) -> None:
            self.pid = pid
            self.return_code = return_code
            self.wait_called = False

        def poll(self) -> int | None:
            return self.return_code

        def wait(self) -> int:
            self.wait_called = True
            self.return_code = 0
            return 0

    backend = FakeProcess(201, return_code=0)
    frontend = FakeProcess(202)

    def fake_start_process(**kwargs):
        seen.append(kwargs)
        if kwargs["name"] == "后端":
            return backend
        return frontend

    monkeypatch.setattr(module, "check_prerequisites", lambda _root: (Path(".venv/bin/python"), "/usr/bin/npm"))
    monkeypatch.setattr(module, "start_process", fake_start_process)
    monkeypatch.setattr(module.os, "killpg", lambda _pid, _signal: None)
    monkeypatch.setattr(module, "build_share_urls", lambda _host, _port: ["http://192.168.1.20:5173"])
    monkeypatch.setattr(module, "is_wsl_environment", lambda: False)

    args = SimpleNamespace(host="127.0.0.1", lan=True, backend_port=8000, frontend_port=5173, open_browser=False)

    assert module.run(args) == 0
    backend_command = seen[0]["command"]
    frontend_command = seen[1]["command"]
    frontend_env = seen[1]["env"]
    assert backend_command[backend_command.index("--host") + 1] == "0.0.0.0"
    assert frontend_command[frontend_command.index("--host") + 1] == "0.0.0.0"
    assert frontend_env["TRANSCRIPT_API_PROXY_TARGET"] == "http://127.0.0.1:8000"


def test_run_lan_mode_prints_wsl_guidance(monkeypatch, capsys) -> None:
    module = load_start_web_module()

    class FakeProcess:
        def __init__(self, pid: int, return_code: int | None = None) -> None:
            self.pid = pid
            self.return_code = return_code

        def poll(self) -> int | None:
            return self.return_code

        def wait(self) -> int:
            self.return_code = 0
            return 0

    backend = FakeProcess(301, return_code=0)
    frontend = FakeProcess(302)

    def fake_start_process(**kwargs):
        if kwargs["name"] == "后端":
            return backend
        return frontend

    monkeypatch.setattr(module, "check_prerequisites", lambda _root: (Path(".venv/bin/python"), "/usr/bin/npm"))
    monkeypatch.setattr(module, "start_process", fake_start_process)
    monkeypatch.setattr(module.os, "killpg", lambda _pid, _signal: None)
    monkeypatch.setattr(module, "build_share_urls", lambda _host, _port: ["http://172.30.98.229:5173"])
    monkeypatch.setattr(module, "is_wsl_environment", lambda: True)
    monkeypatch.setattr(module, "discover_wsl_ipv4_addresses", lambda: ["172.30.98.229"])
    monkeypatch.setattr(module, "discover_windows_lan_addresses", lambda: ["192.168.1.20"])

    args = SimpleNamespace(host="127.0.0.1", lan=True, backend_port=8000, frontend_port=5173, open_browser=False)

    assert module.run(args) == 0
    output = capsys.readouterr().out
    assert "WSL 局域网访问提示" in output
    assert "WSL 内部监听地址" in output
    assert "http://192.168.1.20:5173" in output
    assert "connectaddress=172.30.98.229 connectport=5173" in output
