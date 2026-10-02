---
title: 移除持续消耗 GPU 的背景光球
type: ff
status: open
---

- 做了什么：用户确认在浏览器隐藏背景光球后 GPU 占用下降；删除全局三个装饰光球及专用模糊、混色、无限循环动画和深色模式覆盖。保留普通背景、主题切换、卡片样式和业务逻辑。
- 改了哪些：`frontend/src/App.vue`、`frontend/src/styles/main.css`。
- 怎样验证：`.venv/bin/python -m pytest -q` 361 passed；`frontend/npm run build` 类型检查和生产构建通过（存在大于 500 kB 的 chunk 警告）；本地 TestClient 实际读取构建后的首页和两份 JS/CSS，均返回 200，确认产物不再含 `glow-orb`、`bg-glow-container`、`float-orb`；`git diff --check` 通过。
- 验证边界：未重跑 ASR，未部署或重启 8080 Docker 服务；尚待部署后的浏览器外观与 GPU 复核，不将静态产物检查当成浏览器性能测量。
- 对 codestable/ 的影响：无现有 spec 需要同步；本条保留修改和验证记录，待上线效果确认。
