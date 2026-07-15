---
doc_type: issue-fix
issue: 2026-07-15-large-pdf-ocr-empty-stream
path: standard
fix_date: 2026-07-15
related: [large-pdf-ocr-empty-stream-analysis.md]
tags: [pdf, ocr, codex-api, event-stream, concurrency, memory]
---

# 大型 PDF OCR 空白页失败修复记录

## 1. 实际采用方案

采用用户确认的方案 B，并按用户补充的投递约束实现：

1. 补齐 Responses API 的 `output_text.done`、`content_part.done`、`output_item.done` 和
   `response.completed.response.output` 文本提取。
2. 区分“明确存在但为空的 output_text”与“响应结构缺少 output_text”；前者代表合法空白页，
   后者仍显式报错，不吞掉协议异常。
3. 将整本 PDF 一次性渲染、base64 化改为工作线程按需渲染当前页，单页请求结束后释放图片数据。
4. 保留错峰投递：每 10 秒新增一页，不等待前一页完成；最多允许 20 个同时在途请求。

并发上限属于本次大型 PDF 稳定性修复的必要限制：原实现 `0` 会令 603 页输入理论上创建
603 个线程和数百个活动流。上限触发条件是已有 20 个请求尚未完成；触发后只等待一个请求完成，
随后继续按 10 秒间隔投递。它不截断页面、不伪造成功，也不改变未达到上限时的正常错峰路径。

## 2. 改动文件清单

- `src/codex_lb_client.py`：兼容官方完成事件，正确处理明确的空 output_text。
- `src/reference_utils.py`：改为逐页按需渲染和编码。
- `src/ocr_scheduler.py`：活动请求采用可配置正整数上限，保持定时持续投递与按页码重排。
- `src/schemas.py`、`config/settings.yaml`、`config/setting.yaml`：默认 10 秒投递、最大 20 个在途请求。
- `tests/test_refine.py`：覆盖完成事件、空白页、结构缺失和正文去重。
- `tests/test_prepare_reference.py`：覆盖逐页渲染、请求图片和失败行为。
- `tests/test_ocr_scheduler.py`：覆盖并发上限及每 10 秒持续投递。
- `tests/test_config.py`、`tests/helpers.py`：同步配置校验和测试配置。
- `README.md`：更新大型 PDF 的资源策略与调度说明。
- 本 issue 的 report、analysis 与 fix-note：补充实际运行证据和闭环记录。

## 3. 验证结果

- 针对性回归：85 个相关测试通过。
- 完整回归：`.venv/bin/python -m pytest -q` 通过（最终次数见本轮执行记录）。
- 真实 PDF 结构：样例共 603 页；第 1 页与第 603 页均通过新的单页渲染、base64 编码链路。
- 真实第 2 页：图像确认为空白扫描页；实际 API 请求成功完成，修复后返回空字符串且不再抛错。
- 真实第 3 页：实际 API 请求成功完成，返回 34 个字符，证明非空正文路径未被空白页逻辑误伤。
- 未运行整本 603 页远程 OCR，避免在修复验证阶段产生数小时运行和数百页 API 成本；需由用户从
  Web 页面重新提交整本任务完成最终验收。

## 4. 遗留事项

- 等待用户重新运行 603 页 Web 任务并确认整本 TXT 成功生成。
- 本次不实现方案 C 的逐页检查点和失败续跑；若后续需要避免长任务中途失败后重做，应另开功能需求。
