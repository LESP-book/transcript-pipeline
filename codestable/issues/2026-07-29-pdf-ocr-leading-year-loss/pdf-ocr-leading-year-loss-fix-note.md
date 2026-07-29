---
doc_type: issue-fix
issue: 2026-07-29-pdf-ocr-leading-year-loss
path: fast
status: verified-local
fix_date: 2026-07-29
tags: [pdf, ocr, text-sanitization, year]
---

# PDF OCR 年份缺失修复记录

## 1. 问题与根因

用户提供的《共产党宣言》PDF 是 59 页扫描版，页面图像中明确包含
`1872 年德文版序言`、`1882 年俄文版序言`、`1872 年6月24日于伦敦` 等文字，
但 OCR TXT 中对应内容变成了 `年德文版序言`、`年俄文版序言` 和
`年6月24日于伦敦`。

根因在 `src/reference_utils.py:291-293`：
`strip_leading_ascii_noise()` 原先把行首所有 ASCII 字符（包括 `0-9`）都视为
噪声。`sanitize_gemini_ocr_text()` 会对每一行调用该函数，因此行首年份和日期被
本地清洗逻辑删除；这不是 PDF 缺字，也不是 OCR 页面排序问题。

## 2. 实际修复

- `src/reference_utils.py`：从可删除的行首噪声字符集合中移除数字，保留年份、日期
  及其他数字正文；英文字母和符号噪声仍按原规则清理。
- `tests/test_prepare_reference.py`：补充行首年份、年份标题和日期的回归样例，同时
  保留原有 `t第二节...` 噪声清理断言。

本次没有新增长度、超时、重试、截断或静默回退限制。

## 3. 验证结果

- 针对性测试：`.venv/bin/python -m pytest tests/test_prepare_reference.py -q`，28 passed。
- 全量测试：`.venv/bin/python -m pytest`，265 passed in 4.21s。
- 真实 PDF 检查：`pdfinfo` 确认 59 页；使用项目同一页渲染函数渲染第 2 页成功，
  并用实际页面中的年份/日期样例验证清洗结果保留为
  `1872 年德文版序言` 和 `1872 年6月24日于伦敦`。
- 已人工查看第 1-3 页渲染图，确认页面中的年份确实存在。

## 4. 端到端重跑状态

当前环境未设置 `CODEX_LB_API_KEY` 和 `CODEX_LB_BASE_URL`，因此没有擅自发起 59 页
远程 OCR 重跑。现有 `/home/kuma/下载/共产党宣言.txt` 是修复前产物，不能自动补回
已丢失的数字；需要在配置 OCR API 后重新运行该 PDF，才能生成修复后的完整 TXT。
