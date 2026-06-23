#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_GPU_WHEELS=1
RUN_TESTS=1
RUN_FRONTEND_BUILD=1
RUN_GPU_CHECK=1
UPDATE_BASHRC=1

print_section() {
  printf '\n==> %s\n' "$1"
}

print_ok() {
  printf '[OK] %s\n' "$1"
}

print_warn() {
  printf '[WARN] %s\n' "$1"
}

fail() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
用法：bash scripts/install_wsl2_env.sh [选项]

选项：
  --cpu-only              只安装 CPU 运行环境，不安装 CUDA Python wheels，也不检查 GPU。
  --skip-tests            跳过 .venv/bin/python -m pytest。
  --skip-frontend-build   跳过 npm run build。
  --skip-gpu-wheels       不安装 nvidia-cublas-cu12 / nvidia-cudnn-cu12。
  --skip-gpu-check        不执行 WSL nvidia-smi 与 CTranslate2 CUDA 检查。
  --no-bashrc             不把 CUDA wheel 动态库路径写入 ~/.bashrc。
  -h, --help              显示帮助。
USAGE
}

while (($# > 0)); do
  case "$1" in
    --cpu-only)
      INSTALL_GPU_WHEELS=0
      RUN_GPU_CHECK=0
      ;;
    --skip-tests)
      RUN_TESTS=0
      ;;
    --skip-frontend-build)
      RUN_FRONTEND_BUILD=0
      ;;
    --skip-gpu-wheels)
      INSTALL_GPU_WHEELS=0
      ;;
    --skip-gpu-check)
      RUN_GPU_CHECK=0
      ;;
    --no-bashrc)
      UPDATE_BASHRC=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "未知参数：$1"
      ;;
  esac
  shift
done

require_command() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || fail "未找到命令：$name"
}

is_wsl() {
  [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" ]] && return 0
  [[ -r /proc/sys/kernel/osrelease ]] && grep -Eqi 'microsoft|wsl' /proc/sys/kernel/osrelease
}

python_version_ok() {
  "$1" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)
PY
}

resolve_python312() {
  if command -v python3.12 >/dev/null 2>&1 && python_version_ok python3.12; then
    printf 'python3.12'
    return
  fi
  if command -v python3 >/dev/null 2>&1 && python_version_ok python3; then
    printf 'python3'
    return
  fi
  return 1
}

cuda_wheel_library_path() {
  "$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import importlib.util

paths = []
for name in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
    spec = importlib.util.find_spec(name)
    if spec and spec.submodule_search_locations:
        paths.extend(str(item) for item in spec.submodule_search_locations)
print(":".join(paths), end="")
PY
}

update_bashrc_cuda_path() {
  local library_path="$1"
  local bashrc="$HOME/.bashrc"
  local begin="# transcript-pipeline CUDA runtime BEGIN"
  local end="# transcript-pipeline CUDA runtime END"
  local tmp
  tmp="$(mktemp)"

  if [[ -f "$bashrc" ]]; then
    awk -v begin="$begin" -v end="$end" '
      $0 == begin { skip = 1; next }
      $0 == end { skip = 0; next }
      skip != 1 { print }
    ' "$bashrc" > "$tmp"
  fi

  {
    cat "$tmp"
    printf '\n%s\n' "$begin"
    # CTranslate2 在 WSL2 中需要能找到 CUDA/cuDNN wheel 自带的动态库。
    printf 'export LD_LIBRARY_PATH="%s${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n' "$library_path"
    printf '%s\n' "$end"
  } > "$bashrc"
  rm -f "$tmp"
  print_ok "已写入 ~/.bashrc 中的 CUDA wheel 动态库路径"
}

print_section "运行环境检查"
is_wsl || fail "本脚本需要在 WSL2 Linux 环境中运行。"
print_ok "当前环境是 WSL"

cd "$PROJECT_ROOT"
[[ -f "requirements.txt" ]] || fail "未在项目根目录找到 requirements.txt"
[[ -f "frontend/package-lock.json" ]] || fail "未在项目根目录找到 frontend/package-lock.json"

print_section "APT 基础工具"
require_command sudo
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  ca-certificates \
  curl \
  ffmpeg \
  git \
  libgomp1 \
  nodejs \
  npm \
  poppler-utils \
  python3 \
  python3-pip \
  python3-venv \
  unzip
print_ok "APT 基础工具已安装"

print_section "Python 3.12 与虚拟环境"
PYTHON_BIN="$(resolve_python312 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  fail "项目要求 Python 3.12。建议使用 Ubuntu 24.04 WSL，或先在当前发行版安装 python3.12 与 venv。"
fi
print_ok "使用 $("$PYTHON_BIN" --version)"

"$PYTHON_BIN" -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip wheel setuptools
"$PROJECT_ROOT/.venv/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"
print_ok "Python 依赖已安装"

if [[ "$INSTALL_GPU_WHEELS" -eq 1 ]]; then
  print_section "CUDA/cuDNN Python wheels"
  "$PROJECT_ROOT/.venv/bin/python" -m pip install nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*'
  CUDA_LIBRARY_PATH="$(cuda_wheel_library_path)"
  [[ -n "$CUDA_LIBRARY_PATH" ]] || fail "已安装 CUDA/cuDNN wheels，但没有解析到动态库路径。"
  export LD_LIBRARY_PATH="$CUDA_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  print_ok "当前 shell 已设置 LD_LIBRARY_PATH"
  if [[ "$UPDATE_BASHRC" -eq 1 ]]; then
    update_bashrc_cuda_path "$CUDA_LIBRARY_PATH"
  fi
else
  print_warn "已跳过 CUDA/cuDNN Python wheels 安装"
fi

print_section "前端依赖"
(
  cd "$PROJECT_ROOT/frontend"
  npm ci
)
print_ok "前端依赖已安装"

print_section "基础命令检查"
ffmpeg -version | sed -n '1p'
pdftoppm -v 2>&1 | sed -n '1p'
git --version
curl --version | sed -n '1p'
node --version
npm --version

print_section "Python 包导入检查"
"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import fastapi
import faster_whisper
import pydantic
import pypdf
import rapidfuzz
import uvicorn
import yaml

print("Python imports OK")
PY
print_ok "Python 包导入正常"

if [[ "$RUN_GPU_CHECK" -eq 1 ]]; then
  print_section "WSL2 GPU 检查"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi
  elif [[ -x /usr/lib/wsl/lib/nvidia-smi ]]; then
    /usr/lib/wsl/lib/nvidia-smi
  else
    fail "WSL 中找不到 nvidia-smi。请先确认 Windows NVIDIA 驱动与 WSL 更新完成；没有 GPU 时用 --cpu-only。"
  fi

  "$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import ctranslate2

count = ctranslate2.get_cuda_device_count()
if count < 1:
    raise SystemExit("CTranslate2 没有发现 CUDA 设备。")
print(f"CTranslate2 CUDA device count: {count}")
print("CTranslate2 CUDA compute types:", ", ".join(ctranslate2.get_supported_compute_types("cuda")))
PY
  print_ok "CTranslate2 CUDA 检查通过"
fi

if [[ "$RUN_TESTS" -eq 1 ]]; then
  print_section "后端测试"
  "$PROJECT_ROOT/.venv/bin/python" -m pytest
  print_ok "pytest 通过"
else
  print_warn "已跳过 pytest"
fi

if [[ "$RUN_FRONTEND_BUILD" -eq 1 ]]; then
  print_section "前端构建检查"
  (
    cd "$PROJECT_ROOT/frontend"
    npm run build
  )
  print_ok "前端构建通过"
else
  print_warn "已跳过前端构建"
fi

print_section "安装完成"
printf '本机使用命令：./start_web.sh\n'
printf '局域网使用命令：./start_web.sh --lan\n'
printf '单任务示例：.venv/bin/python scripts/08_run_job.py --video "/path/to/video.mp4" --reference "/path/to/reference.pdf" --output-dir "/path/to/output"\n'
