---
kind: issue
title: WSL2 GPU 单容器部署
type: feature
status: open
created: 2026-09-27
---

# WSL2 GPU 单容器部署

## 做成以后是什么样

单服务 Compose 在 WSL2 原生 Docker Engine 上以 NVIDIA GPU 运行现有 FastAPI、Vue 生产前端和原有业务入口；数据、前端设置及 ASR 模型缓存跨容器重建保留。局域网可信设备可访问，但不部署公网。

**范围：** Dockerfile/Compose/健康检查/静态托管/GPU 验收脚本/部署文档和测试；不容器化互联网 codex-lb，不增加业务阶段或认证，不执行宿主安装/daemon 重启/Windows 网络变更，不自动 commit、push、关闭事项或发起付费请求。

## 当前证据与执行安排

现有 `start_web.sh` 同时运行 Uvicorn 和 Vite；`api_server.create_app` 在进程内维护 `active_jobs` 与线程池，必须单 worker。`src/asr_utils.py` 已预加载 NVIDIA Python wheels；`config/settings.yaml` 将模型缓存定位为 profile `cache_dir` + `asr.model_cache_subdir`。现有 Web 设置保存到 `data/jobs/frontend-settings.json`；代理直连历史见 `codestable/issues/2026-07-20-optional-codex-lb-proxy-bypass/`。前端只调用相对 `/api`。此仓库无 `codestable/spec/` 或 Docker 现存事项，具体行为以当前代码为准。

风险穿刺（2026-09-27）：
1. WSL 驱动链：`/dev/dxg` 可见，`/usr/lib/wsl/lib/nvidia-smi` 报 RTX 3060 Ti / 驱动 591.86；通过。
2. 容器 GPU：本地 WSL2 Unix socket 的 Debian Docker 29.6.1 可达，但 `nvidia-container-toolkit` 未安装，`docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi` 返回 `failed to discover GPU vendor from CDI: no known GPU vendor found`；阻塞，宿主操作需用户授权。
3. 应用 CUDA/真实短音频及默认模型：等待 Toolkit 后验证；绝不把未通过写成通过。
4. 外网 Key/局域网设备：缺授权/设备条件则独立标记待现场验收。

独立交付接缝：API 静态路由与回归测试、容器/文档/GPU 脚本分别在隔离 worktree 由单写者产出 patch；主会话合并验证。原 checkout 预检为干净，`.venv` 缺失后使用 `uv venv .venv` 初始化，`.venv/bin/python -m pytest` 基线 280 通过；`frontend/npm ci && npm run build` 成功。

## 质量与验证

- 功能正确性：静态深链与缺失资源 404，未知 `/api/*` 保留 API 404；用针对性路由测试和 Compose 实测。
- 可靠性：上传/任务状态/下载及停止后中断任务可辨；不承诺自动续跑；用独立数据目录做读写/重建验证。
- 信息安全性：密钥不入镜像/bundle/log，设置接口脱敏，局域网 HTTP 只在可信网络；检查配置与真实响应，不调用付费 API。
- 兼容性：保留 `.venv` + Vite 开发、JSON 主结构与原有路径；全量 pytest 和前端 build。
- GPU 验收须有官方容器实际计算、CTranslate2 计算类型及消费 segments 的转录证据；硬件/runtime 不通则阻塞该目标。

## 实施与验证记录（2026-09-27）

- 已整合 `Dockerfile`、`compose.yaml`、`.dockerignore`、`docker/constraints.txt`、`scripts/check_docker_gpu.py`、FastAPI 静态路由/health、回归测试及部署文档。容器 worker 首版误用 Nginx，已暂停并在同一隔离工作区修正；最终镜像无 Nginx，镜像指令为单 Uvicorn worker 的 exec 形式。
- 全量 `.venv/bin/python -m pytest`：284 passed；前端 `npm ci && npm run build`：通过（既有 bundle 体积提示）；`docker compose config` 与最终镜像构建成功；镜像内 Python 3.12.14 / CTranslate2 4.8.2 / faster-whisper 1.2.1 / CUDA wheels 见交付版本矩阵。只复制已知默认配置/提示词/词汇表；data/.env/自定义配置不进镜像。
- 非 GPU Compose override 的 CPU **隔离验收**：`/api/health`、生产首页/深链/真实 JS asset、未知 API/丢失资源 404；上传独立 `refined_json`、查询 export-markdown 任务状态、下载 ZIP 含 `final/source.md` 和 `.txt`；设置接口 Key 脱敏、实际 profile 为 local_cpu。验收数据 `/tmp/transcript-docker-accept-data`，任务 `0f4a3da58819`，日志/状态实际存在；重建后 data、设置和缓存卷标记保留。正常 stop/start 后合成 pending 状态修正为 failed/partial，强制退出后的合成 pending 状态修正为 failed；不等同于真实长任务在途测试。只删除验收容器/网络，未用 `down -v`。
- GPU 路径仍阻塞：官方 CUDA 基础容器 `--gpus all` 失败 `failed to discover GPU vendor from CDI`；默认 GPU Compose 的隔离 `up` 失败 `could not select device driver "nvidia" with capabilities: [[gpu]]`。在无 GPU 运行的镜像中 CTranslate2 device_count=0，脚本明确非零退出，无 CPU 静默回退。官方 CUDA 实际计算、CUDA 转录（small 与 large-v3-turbo）、模型真实缓存复用、项目 ASR JSON/TXT 均**未验收**。
- 独立 readonly bind `/app/data` 权限负测：健康 200，但写设置接口 500，日志明确 `Read-only file system`；远端真实 API、另一台 LAN 设备、活跃任务的 SIGTERM/SIGKILL 尚未验收。已做独立只读源码 review，无源代码问题发现，GPU/网络现场验收仍未完成。

## 后续小改：一键部署入口和服务命名

- 2026-09-27 用户在 WSL 内自行安装 Toolkit、注册 NVIDIA runtime 并重启 Docker；其日志显示应用 CTranslate2 设备 count=1、float16，可用实际容器转录产出 1640 / 1086 segments 的 JSON/TXT，LAN 请求、远端 codex_api 和最终稿导出走通。历史 Toolkit 缺失仅代表原始预检状态；没有据此声称官方 CUDA 独立计算或真实缓存免重下已验证。
- `compose.yaml` 唯一服务名改为 `trans`，原 `app` 容器不自动迁移；新增 `scripts/deploy_docker_wsl2.sh`，支持只读 `--check`、交互确认（或显式 `--yes`）后安装缺失的 WSL 原生 Docker Engine/Compose、NVIDIA Container Toolkit，按需备份 daemon 配置和重启 Docker，再构建/健康启动 `trans`。对当前运行中的旧 `app` 容器先阻断，防止端口冲突或中断进程内任务；不修改 Windows 网络/驱动、不 chown 数据、不 `down -v`。同步 README、Docker 运维文档及脚本/Compose 契约测试。
- 验证：`.venv/bin/python -m pytest` 286 passed，`docker compose config --quiet`、`bash -n` 通过；现场 `--check` 正确发现运行中的 `transcript-pipeline-app-1` 并拒绝部署。**未执行**有副作用的 `--yes` / daemon 安装重启 / 停止旧任务 / 新 `trans` 启动；须待用户确认旧任务空闲、手动迁移后作真实新服务验收。

未获授权不得执行 daemon/toolkit 安装重启、Windows 防火墙/WSL 网络变更或 paid API 调用。本事项保持 open；关闭与稳定规格毕业另需用户授权。
