---
doc_type: issue-fix
issue: 2026-07-11-pdf-ocr-pagewise-requests
path: standard
status: pending-provider-verification
fix_date: 2026-07-11
related: [pdf-ocr-pagewise-requests-analysis.md]
tags: [pdf, ocr, codex-api, pagewise-requests]
---

# 多页 PDF OCR 上下文超限修复记录

## 1. 实际采用方案

采用分析中的方案 A：PDF 页面渲染完成后，先以 PDF 元数据页数验证所有
`page-N.png` 均存在且页号连续；随后每页单独提交一个仅含一张图片的
Codex API 请求。所有页面请求均成功后才按页码顺序
直接拼接并写出 OCR sidecar，因此不会在跨页位置额外插入换行。

任一页面渲染缺失或请求失败时，处理会携带具体页码失败，且不会写出部分 OCR
sidecar。短标题页或图片页不因文本较短而被误判失败；最终全文仍沿用既有的
有效文本校验。

## 2. 改动文件清单

- `src/reference_utils.py`
  - 新增 PDF 页数读取与渲染页号完整性校验。
  - 将 Codex API OCR 从单次多图片请求改为逐页单图片请求。
  - 将每页 OCR 成功作为合并与写入 sidecar 的前置条件。
- `tests/test_prepare_reference.py`
  - 覆盖缺页拒绝、双位页码的数值排序、逐页请求、跨页无额外换行及中途失败不写部分结果。
- `README.md`
  - 更新 Codex API PDF OCR 的逐页提交与完整性保证说明。
- `codestable/issues/2026-07-11-pdf-ocr-pagewise-requests/`
  - 保存 report、analysis 与本修复记录。

未改动其他 OCR 后端、任务 API 协议、上游 JSON 主结构或配置中的超时/页数限制。

## 3. 验证结果

- `.venv/bin/python -m pytest tests/test_prepare_reference.py`：26 passed。
- `.venv/bin/python -m pytest`：196 passed。
- `.venv/bin/python -m compileall -q src/reference_utils.py tests/test_prepare_reference.py`：通过。
- 真实 PDF 本地渲染：`《欧洲哲学史》20260623.pdf` 的 PDF 元数据页数为 6，实际渲染并校验得到 6 张图片；首尾图像均成功读取。
- 真实远程 OCR：使用 `gpt-5.4-mini` 发起第 1 页的单页请求时，codex-lb 返回 HTTP 429 `account_stream_cap`，错误说明所有上游账号不可用。请求未到达模型，不能作为本修复的端到端结果；未重试。
- `git diff --check`：通过。

## 4. 遗留事项

需要等待 codex-lb 上游账号恢复后，通过 Web 设置页对一份多页扫描 PDF 运行
一次 `codex_api` OCR，确认 codex-lb 中每页对应一条请求且最终结果完整后，将
本记录的 `status` 更新为 `verified`。本次用于验证的用户提供密钥未写入项目文件
或设置；由于其曾在交互式终端中输入，建议用户在 codex-lb 侧轮换该密钥。
