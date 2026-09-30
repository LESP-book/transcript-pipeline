---
type: ff
status: open
---

# Docker 部署补齐 Qwen 依赖

- 做了什么：Compose / WSL2 部署默认安装 Whisper + Qwen；支持 ASR_BACKENDS=whisper/qwen/funasr/all，sudo 路径显式传递，非法值在宿主检查/修改前拒绝。不改变默认转录模型；直接 docker build 仍默认 Whisper。
- 改了哪些：compose.yaml、scripts/deploy_docker_wsl2.sh、tests/test_docker_deploy.py、docs/DOCKER.md、docs/ASR_BACKENDS.md。
- 怎么验证：`.venv/bin/python -m pytest` 361 passed；真实 `bash scripts/deploy_docker_wsl2.sh --check` 通过；Docker Compose 实际展开默认 qwen 和显式 whisper 参数符合预期；测试覆盖全部选项在普通/sudo 包装路径传递及非法值拒绝；git diff --check 通过。
- 对 codestable/ 的影响：补充 002 Docker 与 005 ASR 事项的历史结论——此前默认部署仅 Whisper；此次 Compose 默认携带 Qwen 依赖，但默认识别模型仍不变。无 Project Spec 可同步。
- 待确认：未构建新镜像、未重启现有服务、未跑真实转录，避免打断在线任务；用户完成重新部署并确认网页可选后再收尾。此次验证不代表新镜像 GPU 推理验收。
