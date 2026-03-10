from __future__ import annotations

import os

from src.local_helper_api_cli import main


def test_local_helper_api_cli_forwards_args_to_uvicorn(monkeypatch) -> None:
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

    monkeypatch.setattr("src.local_helper_api_cli.uvicorn.run", fake_run)

    exit_code = main(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "28011",
            "--remote-api-base-url",
            "http://127.0.0.1:8000",
            "--profile",
            "windows_gpu",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "app": "src.local_helper_api:create_default_app",
        "host": "127.0.0.1",
        "port": 28011,
        "reload": False,
        "factory": True,
    }
    assert "TRANSCRIPT_REMOTE_API_BASE_URL" not in os.environ
    assert "TRANSCRIPT_PROFILE" not in os.environ
