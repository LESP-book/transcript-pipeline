---
doc_type: issue-fix
issue: 2026-07-20-stage6-overstrict-delivery-validation
path: standard
fix_date: 2026-07-20
related: [stage6-overstrict-delivery-validation-analysis.md]
tags: [refine, validation, markdown, retry, codex-api]
---

# 阶段 6 交付校验过严修复记录

## 1. 实际修复

按用户确认的方案 C 完成最小修改：

1. 最终稿不再强制以一级标题开头，也不再强制标题后存在空行和正文。
2. 保留程序回退结构化标记、Unicode 替换字符 `�`、明确 `# source` 占位标题三项检查。
3. 重试提示同步移除强制 H1 与固定空行要求，避免重试时再次向模型施加已经取消的契约。
4. README 和两份配置示例的注释同步为实际规则。

JSON 顶层对象与非空 `final_markdown` 继续由原有解析链校验，没有复制到最终交付校验中。

## 2. 修改文件

- `src/refine_utils.py`：精简最终交付校验和重试提示。
- `tests/test_refine.py`：新增 JSON 非空契约、无 H1 接受、确定性坏结果拒绝及零重试写盘回归。
- `config/settings.yaml`、`config/setting.yaml`：更新既有重试配置注释。
- `README.md`：记录阶段 6 的 JSON 契约与最终交付校验边界。
- 本 issue 的 report / analysis / fix-note：记录证据、决策、影响和验证结果。

## 3. 验证结果

### 自动化测试

- 阶段 6 与诊断定向测试：`52 passed in 0.51s`。
- 全量命令：`.venv/bin/python -m pytest`。
- 全量结果：`262 passed in 5.59s`。
- `py_compile` 与 `git diff --check` 通过。

### 真实脚本样例

使用真实入口 `scripts/06_refine.py` 和本机 HTTP/SSE 模拟服务运行一个无参考文本样例。服务返回合法
JSON，`final_markdown` 首行是普通正文，后续才出现二级标题：

- `total=1, success=1, skipped=0, failed=0, backends=codex_api`。
- `validation_retry_count=0`，证明未制造第二次请求。
- 诊断汇总只有一条 `accepted`，`validation_reasons=[]`。
- 临时样例目录：`/run/user/1000/codex-desktop/tmp/transcript-stage6-scheme-c.ru63tnbi`。

另外用本地已有的三个真实阶段 6 产物复核：三个“首行是正文”的结果均通过新校验；一个以
`# source` 开头的旧占位结果仍被拒绝。

## 4. 影响检查

- 调用链：最终校验仍只由 `run_validated_single_pass_backend_refinement` 调用；签名和返回结构未变。
- 状态与诊断：accepted / rejected 结构未变，只减少两个不再产生的原因枚举。
- 重试：次数配置未变；程序回退、乱码和占位标题仍按原路径重试并在最终无效时明确失败。
- 网络：未修改 HTTP/SSE 客户端、redworker 地址或其上游 WebSocket 行为。
- 上下游：未回改 ASR、参考文本或已存在产物；阶段 7 仍接收同一 `final_markdown` 字段。

## 5. 已知边界

本次不判断段落顺序、内容覆盖率或文稿语义质量，也不改变 redworker 的上游 WebSocket。部署到远端
WSL 后仍需由用户用原三视频批量任务验证：第一次已完成的合法响应应直接被接受；如果第一次请求自身
返回 `response.failed/stream_incomplete`，则仍属于服务商上游链路问题，应凭诊断中的 response ID
继续定位。
