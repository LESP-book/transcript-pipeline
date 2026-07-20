from __future__ import annotations

import json
import os
from pathlib import Path

from src.web.frontend_settings import FrontendSettings, codex_lb_environment, load_frontend_settings


def test_legacy_frontend_settings_default_proxy_bypass_to_disabled(tmp_path: Path) -> None:
    settings_path = tmp_path / "data/jobs/frontend-settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"codex_lb_base_url": "https://api.redworker.org"}),
        encoding="utf-8",
    )

    settings = load_frontend_settings(tmp_path)

    assert settings.codex_lb_bypass_proxy is False


def test_codex_lb_environment_bypasses_proxy_only_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "localhost,company.internal")
    monkeypatch.setenv("no_proxy", "legacy.internal")
    settings = FrontendSettings(
        codex_lb_base_url="https://api.redworker.org",
        codex_lb_bypass_proxy=True,
    )

    with codex_lb_environment(settings):
        entries = os.environ["NO_PROXY"].split(",")
        assert os.environ["NO_PROXY"] == os.environ["no_proxy"]
        assert set(["localhost", "company.internal", "legacy.internal", "api.redworker.org"]).issubset(entries)
        assert entries.count("api.redworker.org") == 1

    assert os.environ["NO_PROXY"] == "localhost,company.internal"
    assert os.environ["no_proxy"] == "legacy.internal"


def test_codex_lb_environment_keeps_proxy_routing_when_switch_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.delenv("no_proxy", raising=False)
    settings = FrontendSettings(
        codex_lb_base_url="https://api.redworker.org",
        codex_lb_bypass_proxy=False,
    )

    with codex_lb_environment(settings):
        assert os.environ["NO_PROXY"] == "localhost"
        assert "no_proxy" not in os.environ

    assert os.environ["NO_PROXY"] == "localhost"
    assert "no_proxy" not in os.environ
