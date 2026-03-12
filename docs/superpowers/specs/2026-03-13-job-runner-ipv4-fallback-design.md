# Job Runner 网页抓取 IPv4 回退设计

## 目标

当 `scripts/08_run_job.py` 通过网页链接抓取参考原文时，如果默认网络路径出现 `Network is unreachable` 一类错误，自动回退到 IPv4 解析后重试一次。

## 范围

- 仅修改 `src/job_runner.py` 中网页参考抓取路径
- 为该回退路径补充测试

## 非目标

- 不引入新的 HTTP 客户端依赖
- 不修改本地 `txt/md/pdf` 参考输入逻辑
- 不增加代理、认证、通用重试策略
- 不改动后续参考提取、阶段调度和输出结构

## 方案

1. 保持当前默认 `urlopen()` 请求路径不变
2. 若首次请求抛出网络不可达类错误，则临时将 DNS 解析限制为 IPv4，并使用同一请求对象再试一次
3. 若仍失败，保持现有错误语义，继续抛出 `网页参考抓取失败`

## 兼容性

- 正常网络环境下行为不变
- 仅在网络层失败时触发附加回退
- 对 HTML/PDF 内容提取逻辑无影响

## 验证

- 定向测试：首次失败、IPv4 回退成功
- `.venv/bin/python -m pytest tests/test_job_runner.py`
- `.venv/bin/python -m pytest`
- 如环境允许，再执行一次真实 `scripts/08_run_job.py` 命令验证
