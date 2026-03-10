from __future__ import annotations

from src.remote_api_cli import main


def test_remote_api_cli_forwards_args_to_uvicorn(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app, host, port, reload, factory) -> None:
        captured.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "factory": factory,
            }
        )

    monkeypatch.setattr("src.remote_api_cli.uvicorn.run", fake_run)

    exit_code = main(["--host", "0.0.0.0", "--port", "9000", "--reload", "--profile", "windows_gpu"])

    assert exit_code == 0
    assert captured == {
        "app": "src.remote_api:create_default_app",
        "host": "0.0.0.0",
        "port": 9000,
        "reload": True,
        "factory": True,
    }
