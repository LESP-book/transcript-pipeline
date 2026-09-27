from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy_docker_wsl2.sh"


def test_docker_deploy_script_has_safe_entrypoints() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    help_result = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True, check=True)
    assert "--check" in help_result.stdout
    assert "--yes" in help_result.stdout
    assert "trans" in help_result.stdout

    unknown_result = subprocess.run(
        ["bash", str(SCRIPT), "--unknown"], capture_output=True, text=True, check=False
    )
    assert unknown_result.returncode != 0
    assert "未知参数" in unknown_result.stderr


def test_compose_uses_only_trans_service_and_preserves_gpu_volume() -> None:
    config = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert list(config["services"]) == ["trans"]
    service = config["services"]["trans"]
    assert service["deploy"]["resources"]["reservations"]["devices"][0]["capabilities"] == ["gpu"]
    assert "./data:/app/data" in service["volumes"]
    assert "model-cache:/home/app/.cache/transcript-pipeline" in service["volumes"]
