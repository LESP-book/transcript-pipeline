---
doc_type: issue-fix
issue: 2026-07-19-stage6-refine-failure-observability
path: standard
fix_date: 2026-07-19
related: [stage6-refine-failure-observability-analysis.md]
tags: [refine, codex-lb, sse, diagnostics, artifacts]
---

# 阶段 6 校对失败不可观测修复记录

## 1. 实际采用方案

采用 analysis 中确认的方案 B：为阶段 6 的每次后端尝试建立独立诊断目录，并在
`paths.logs_dir/refine/diagnostics.json` 生成稳定汇总索引。

诊断链覆盖：

1. 脱敏请求摘要：模型、reasoning、端点、代理、Prompt 长度和 SHA-256，不保存 Prompt 正文、
   Authorization 或 API Key。
2. 传输证据：urllib / curl、HTTP 状态、curl 退出码和 stderr、本地与远端地址、HTTP 版本、DNS /
   连接 / TLS / 首字节 / 总耗时、下载字节数，以及完整或中断时已收到的 SSE。
3. 协议与正文证据：SSE 事件计数、终止事件、`response_id`、畸形 JSON 事件数、提取正文和解析后的
   JSON。
4. 业务校验证据：请求后端、实际后端、程序回退、锁定引用变化、Markdown 校验原因、重试尝试号及
   最终 accepted / rejected 状态。
5. 任务产物：汇总 JSON 通过现有任务产物 API 以“阶段 6 调用诊断”暴露；完整响应只保留在任务目录。

本次没有修改模型、Prompt 业务内容、并发数、既有超时、既有重试次数、校验规则、程序回退规则或
代理路由，也没有新增截断、自动清理和保留天数。

诊断写盘失败时采用显式 warning 旁路：触发条件是目录权限、磁盘空间或 JSON 序列化异常；目的是
避免可观测能力反过来把原本合法的模型响应判为失败；影响范围只限诊断文件可能缺失，阶段 6 原成功
路径和返回结构不变。对应测试验证了目录不可写时成功结果仍会返回。

## 2. 改动文件清单

- `src/request_trace.py`：新增脱敏元数据、原子诊断写入、按尝试建立目录和汇总索引。
- `src/codex_lb_client.py`：为 urllib / curl / SSE 增加可选诊断上下文，保留部分响应、传输指标、
  SSE 摘要和协议错误；curl 改为字节接收后显式 UTF-8 容错解码，避免非法字节使证据链自身中断。
- `src/refine_utils.py`：把诊断上下文接入阶段 6 单次调用与输出校验，记录解析错误、程序回退、锁定
  引用和每次校验结论。
- `src/web/artifacts.py`：新增 `refine-diagnostics` 任务产物。
- `tests/test_refine_diagnostics.py`：覆盖成功、curl 部分断流、服务端完成但模型正文非 JSON、诊断写盘
  失败四条路径。
- `tests/test_refine.py`：覆盖一次拒绝后重试成功、重试后仍拒绝的汇总记录。
- `tests/test_api_server.py`：覆盖诊断汇总产物的列出与读取。
- `README.md`：补充诊断位置、文件内容、安全边界和磁盘影响。
- 本 issue 的 report / analysis / fix-note：保留问题、方案和验证证据。

## 3. 验证结果

### 自动化测试

- 命令：`.venv/bin/python -m pytest`
- 结果：`258 passed in 6.54s`。
- 相关定向回归：阶段 6、PDF OCR、任务产物共 `77 passed`。
- 静态基础检查：`py_compile` 与 `git diff --check` 通过；项目环境未安装 ruff，未伪报其结果。

### 实际脚本样例

使用本机 HTTP SSE 模拟服务运行真实命令：

```bash
.venv/bin/python scripts/06_refine.py --config <临时配置> --backend codex_api
```

第一次因临时样例缺少同 basename 参考文本，被现有输入契约明确拒绝；补齐参考文本后运行成功：

- `total=1, success=1, skipped=0, failed=0, backends=codex_api`
- refined JSON 正常写出 `# 诊断样例` 和正文。
- 汇总状态为 `accepted`，记录 `HTTP 200`、`response.completed` 和
  `resp_local_real_sample`。
- 尝试目录写出 request / transport / raw SSE / SSE summary / extracted output / parsed output /
  outcome / validation 等证据。
- 对整个诊断目录扫描，未发现测试 API Key `local-sample-secret`。

样例目录：`/tmp/transcript-refine-diagnostics.tNlo9M`。

## 4. 遗留事项

1. 本轮解决的是“失败证据丢失”，尚未凭空断言现场乱码根因已经修复。需要部署到用户的远端 WSL，
   再跑一组三视频任务，用新证据判断究竟是 curl / HTTP2 断流、SSE 不完整、模型正文非 JSON、结果
   契约错误，还是 Markdown / 锁定引用校验拒绝。
2. 完整 SSE 和模型正文可能包含任务内容，且当前按要求不截断、不自动清理；部署后需观察磁盘增长，
   再依据真实用量单独设计可配置保留策略，不能无依据提前截断。
3. 当前 Web 只读取汇总 JSON，不直接下载完整 SSE；需要深挖时按汇总中的
   `diagnostic_directory` 到任务日志目录读取证据包。
4. 本地实现尚未同步到另一台电脑的 `~/code/transcript-pipeline`，也未重启其服务或调用付费远端 API。
