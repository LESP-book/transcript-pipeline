from pathlib import Path
import os
import subprocess

import pytest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy_docker_wsl2.sh"


def test_docker_deploy_script_has_safe_entrypoints() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    help_result = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True, check=True)
    assert "--check" in help_result.stdout
    assert "--yes" in help_result.stdout
    assert "trans" in help_result.stdout
    assert "ASR_BACKENDS" in help_result.stdout

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
    assert service["build"]["args"]["ASR_BACKENDS"] == "${ASR_BACKENDS:-qwen}"


def test_deploy_rejects_invalid_asr_backend_before_host_changes() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--check"], capture_output=True, text=True,
        env={**os.environ, "ASR_BACKENDS": "invalid"},
    )
    assert result.returncode != 0
    assert "ASR_BACKENDS 必须是" in result.stderr


@pytest.mark.parametrize("backend", ["", "whisper", "qwen", "funasr", "all"])
@pytest.mark.parametrize("use_sudo", [0, 1])
def test_deploy_passes_asr_backend_through_compose_wrapper(backend: str, use_sudo: int) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    # Execute the actual initialization and wrapper, without any host operations.
    initialization = source.split('export ASR_BACKENDS=', 1)[1].split('esac', 1)[0]
    wrapper = source.split('dc() {', 1)[1].split('\n}', 1)[0]
    shell = 'export ASR_BACKENDS=' + initialization + 'esac\n'
    shell += '''
fail() { exit 2; }
sudo() { (
    unset ASR_BACKENDS
    test "$1" = env
    shift
    while [[ "$1" == *=* ]]; do export "$1"; shift; done
    "$@"
); }
docker() { printf '%s\\n' "$ASR_BACKENDS" "$@"; }
'''
    shell += f'USE_SUDO={use_sudo}\nAPP_UID=1000\nAPP_GID=1000\n'
    shell += 'dc() {' + wrapper + '\n}\ndc build trans\n'
    result = subprocess.run(
        ["bash", "-eu", "-c", shell], capture_output=True, text=True, check=True,
        env={**os.environ, "ASR_BACKENDS": backend},
    )
    assert result.stdout.splitlines() == [backend or "qwen", "compose", "build", "trans"]
