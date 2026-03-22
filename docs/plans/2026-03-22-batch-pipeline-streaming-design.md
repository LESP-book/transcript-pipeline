# 批处理流水推进设计

## 背景

当前批处理入口 [`scripts/09_run_batch_jobs.py`](/home/kuma/programes/transcript-pipeline/scripts/09_run_batch_jobs.py) 调用 [`run_batch_jobs()`](/home/kuma/programes/transcript-pipeline/src/job_runner.py)，按“整批先完成同一阶段，再进入下一阶段”的方式推进：

- `extract-audio`
- `transcribe`
- `prepare-reference`
- `refine`
- `export-markdown`

这会导致前面的 job 即使已经完成 `transcribe`，也必须等待后续 job 全部完成本地转写，才能进入 OCR / refine。

## 目标

只改批处理调度层，让单个 job 在完成 `transcribe` 后立刻进入远程阶段流水线，尽早产出结果。

本次设计必须满足：

- 不改 `prepare-reference` / `refine` / `export-markdown` 的内部逻辑
- 不引入新的并发参数
- 继续使用现有 `remote_concurrency`
- 保持批处理 summary 结构兼容

## 方案

采用“本地串行 + 远程流水”的最小改动方案：

1. 主线程继续按 job 顺序执行本地阶段：
   - `extract-audio`
   - `transcribe`
2. 某个 job 一旦完成 `transcribe`，立刻提交一个远程流水任务：
   - `prepare-reference`
   - `refine`
   - `export-markdown`
3. 远程流水任务通过 `ThreadPoolExecutor(max_workers=remote_concurrency)` 控制并发数量。
4. 每个远程 worker 负责一个 job 的完整远程链路，避免额外引入阶段级优先队列。

## 为什么这样设计

- 符合 KISS：不做 DAG 调度器，不做复杂状态机
- 符合 YAGNI：当前仅解决批量耗时问题，不提前支持单 job 内部的更多并行
- 保持阶段边界：仍然通过现有 `run_stage()` 调用阶段逻辑
- 保持 `remote_concurrency` 的语义简单：仍然表示远程链路同时处理的 job 数

## 数据流

单个 job 的推进顺序变为：

1. `extract-audio`
2. `transcribe`
3. 提交远程任务
4. `prepare-reference`
5. `refine`
6. `export-markdown`
7. 标记 `success`

失败处理：

- 任一阶段失败，当前 job 直接标记 `failed`
- 失败 job 不再进入后续阶段
- 其他 job 继续执行，不受影响

## 并发约束

- `remote_concurrency` 继续作为唯一的远程并发参数
- 它不再表示“单个阶段的并发数量”，而是“远程流水链路的并发 job 数”
- 由于 `prepare-reference` 相对较短，实际效果上仍主要限制 `refine` 的并发数量

## 测试策略

新增批处理调度测试，证明：

1. `job-a` 完成 `transcribe` 后，`prepare-reference` 可在 `job-b` 仍处于 `transcribe` 时启动
2. `prepare-reference` 失败时，当前 job 不进入 `refine` / `export-markdown`
3. 成功 job 仍会复制最终 Markdown 到输出目录

## 范围边界

本次不做：

- 单个 job 内部 ASR 与 OCR 并行
- 新的 `refine_concurrency` 参数
- 通用 DAG 调度器
- 中间 JSON 结构调整
- 阶段内部逻辑修改
