---
kind: issue
title: ASR 多后端接入与真实模型穿刺
type: feature
status: open
created: 2026-09-30
---

# ASR 多后端接入与真实模型穿刺

## 目标与边界

按用户提供的多后端方案，让 CLI、Web 单任务、批量、阶段和阶段文件运行选择稳定候选：`whisper-existing`、`qwen3-asr-1.7b`、`qwen3-asr-0.6b`、`paraformer-zh`、`fun-asr-nano`。旧任务未指定候选时保持 Whisper 行为；新候选不能继承 Whisper compute type/beam/model，也不能失败后偷偷回退。

先完成依赖和真实推理穿刺，再做公共适配、配置快照/入口贯通、Web 与真实对比。未打通真实模型前不铺开 UI，不把 mock 或包元数据查询当作接入验收。

统一 JSON/TXT 保留现有字段；新增可选 metadata 记录实际模型/revision、参数、运行版本、时间戳来源与粒度、分块、告警。时间戳必须对应真实音频区间。不同候选用独立任务/工作区，不覆盖历史结果；旧任务不受后来全局默认变化影响。新依赖按需导入，不要求基础 Whisper 安装携带全部依赖。

不做自动多模型运行、投票/合并、默认模型自动变更、说话人识别、实时服务、微调、OCR/阶段 6/导出改造、历史任务全量重跑、独立模型服务平台。常规事项保持 open，不 commit/push 或自动关闭。

## 当前进展（续轮，初始阻塞已解除）

用户要求继续既定方案后，使用隔离 Python 3.12 worker 环境，保持原 Web/Whisper `.venv` 包版本不变。四个新增模型已真实穿刺并接入公共入口；CLI/API/Web 候选与任务快照已实现。最新真实验收与未完成项见文末“续轮实现与验收”；下面的初始依赖阻塞保留为历史证据，**不是当前停止点**。

## 初始调用链（实现前）

任务/阶段配置 → `scripts/02_transcribe.py` → `src/asr_utils.py::transcribe_batch` → 加载一次 faster-whisper → 完整消费 segments → JSON/TXT。校验和加载仍写死 faster-whisper；Whisper 的 CUDA wheels 预加载也在该模块内。新增后端尚未实现。

项目没有当前 `codestable/spec/` 或相关 ASR Epic。Docker 历史记录见 `002-o-docker-wsl2-gpu-deployment.md`，历史失败不代表今天的状态。

## 初始穿刺风险与实测（2026-09-30，历史记录）

| 风险 | 打通条件 | 本轮证据/状态 |
|---|---|---|
| 现有链回归 | .venv 全量测试和真实 Whisper 输出 | 292 tests passed；25 秒中文语音 CUDA 转录成功，8 段，JSON/TXT 已核查 |
| SDK 与原环境共存 | 实际安装/导入新依赖，旧应用和 Whisper 再次验证 | 只完成 dry-run；保持所有原包版本不变的解析失败，尚未安装 |
| Qwen 两模型与对齐 | 两模型均实际推理得到非空文本和 ForcedAligner 时间戳 | 模型 API 元数据可获取；权重获取、加载、推理、时间戳均未验收 |
| Paraformer/Nano 时间戳 | 固定 checkpoint 与真实音频区间对应 | 仅查询模型元数据；未安装/推理；Nano 不假定能返回字级时间戳 |
| 长音频、静音、下游兼容 | 新引擎跨分块/短音频/静音实际输出与下游读取 | 未验证；不进入 UI 或宣布全后端接入完成 |

### 原环境与 GPU

- 宿主项目 `.venv`：Python 3.13.5；faster-whisper 1.2.1；CTranslate2 4.7.1；numpy 2.4.3；FastAPI 0.135.1；pydantic 2.12.5；huggingface-hub 1.6.0。
- NVIDIA wheels：nvidia-cublas-cu12 12.9.1.4、nvidia-cudnn-cu12 9.20.0.48。PyTorch、torchaudio、Transformers、qwen-asr、funasr 未安装。
- `/usr/lib/wsl/lib/nvidia-smi` 可用：RTX 3060 Ti，8192 MiB，驱动 591.86，驱动宣告 CUDA 13.1；不等于已安装 PyTorch CUDA runtime 版本。
- CTranslate2 实测 CUDA device count=1。`nvidia-smi` 不在 PATH 不代表没有 GPU。
- 当前运行中的 `transcript-pipeline-trans-1` 有 NVIDIA DeviceRequests，`docker exec ... nvidia-smi` 实测能看到同一 GPU。本轮**没有**进行容器内模型转录或 PyTorch 计算，未重建镜像/重启服务。

### 依赖解析结果与停止原因

1. `uv pip install --python .venv/bin/python --dry-run qwen-asr==0.0.6 funasr==1.3.0 torch==2.8.0 torchaudio==2.8.0 -r requirements.txt` 解析成功，但会卸载/替换 4 个现有包：
   - huggingface-hub 1.6.0 → 0.36.2；
   - nvidia-cublas-cu12 12.9.1.4 → 12.8.4.1；
   - nvidia-cudnn-cu12 9.20.0.48 → 9.10.2.21；
   - starlette 0.52.1 → 1.7.0（解析到 Gradio 6.17.3 等未锁定传递依赖）。
2. 导出当前所有 installed distributions 为约束，重跑解析失败：torch 2.8.0 固定要求上述较旧 CUDA wheels，不能同时保留现有版本。
3. 单独 Qwen + 原约束也失败：qwen-asr 0.0.6 固定 Transformers 4.57.6，后者要求 huggingface-hub >=0.34.0,<1.0，与当前 1.6.0 冲突。这与试选 torch 版本无关。
4. 另试 funasr 1.4.16 + torch/torchaudio 2.8.0 + 原约束，同样首先失败于 cuBLAS 约束。不能据此推断所有 FunASR/PyTorch 组合都不可行。
5. `.venv/bin/python -m pip check`：No broken requirements found。没有安装、升级或降级原环境包。

**准确结论：** 当前 SDK 组合无法在“原有每个包版本完全不变、仅追加安装”的条件下解析。未证明调整版本后不能共存，也未证明 CUDA wheels 降级会破坏 Whisper。干跑不是实际安装/运行验收，试选版本不是经过验证的部署锁定版本。

按用户方案的停止条件，暂停在穿刺阶段，报告版本取舍。建议先选择隔离 Python 3.12 的推理穿刺环境，避免在原 `.venv` 中直接执行该未审定安装计划；它不是已批准或已实现的独立服务架构。也可以选择受控原环境版本调整，但必须先确定锁定组合、可恢复原环境，并重复 Whisper/Web 回归。未决定这一步前不扩展前端或把未验证依赖写成正式 requirements。

### 模型元数据（不代表权重下载成功）

Hugging Face API 实际查询得到：

| 模型 | 查询时 revision |
|---|---|
| Qwen/Qwen3-ASR-1.7B | 7278e1e70fe206f11671096ffdd38061171dd6e5 |
| Qwen/Qwen3-ASR-0.6B | 5eb144179a02acc5e5ba31e748d22b0cf3e303b0 |
| Qwen/Qwen3-ForcedAligner-0.6B | c7cbfc2048c462b0d63a45797104fc9db3ad62b7 |
| FunAudioLLM/Fun-ASR-Nano-2512 | 272c57b82523ada6fd87095e955f8e29100979ab |
| funasr/paraformer-zh | d7811ee3ac581fbcfdeb37c98c6ba674028433dc |

这些只是穿刺候选，未作为项目正式模型锁定；Nano remote code 尚未审查或执行。API 可访问不等于大权重一定可获取。

SDK 依据：
- https://github.com/QwenLM/Qwen3-ASR （官方 Transformers + ForcedAligner 接口；SDK 可能已有长音频处理，实际还需检查）。
- https://raw.githubusercontent.com/QwenLM/Qwen3-ASR/main/pyproject.toml （查询时 qwen-asr 0.0.6）。
- https://pypi.org/pypi/qwen-asr/0.0.6/json
- https://pypi.org/pypi/transformers/4.57.6/json
- https://pypi.org/pypi/torch/2.8.0/json
- https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512/blob/main/README.md

## 真实 Whisper 基线与证据位置

隔离产物目录：`data/output/logs/asr-spike-20260930/`（由现有 gitignore 覆盖；没有修改共享 settings 或历史任务）。

原录音 `data/jobs/354d91482b3b/input/audio/source.wav` 只读，ffmpeg 截取原始时间 [120,145] 秒到 `audio/sample.wav`（16kHz/单声道/25 秒）。这是 Whisper 基线，不是新增引擎长音频验收或质量对比。

最终可复现命令：

```bash
.venv/bin/python scripts/02_transcribe.py \
  --config data/output/logs/asr-spike-20260930/whisper-settings.yaml \
  --profile wsl2_gpu_high_accuracy
```

产物：`whisper-existing/sample.json`、`whisper-existing/sample.txt`；模型 large-v3-turbo、CUDA float16、beam 8，保留原有 VAD 与解码行为。

已检查非空全文、8 个唯一 segment ID、有限时间、顺序、全文与 segments/TXT 一致。尾段 end=25.08 秒，相对实际片长超出 0.08 秒，属于原有 Whisper 边界偏差；本轮不顺手修改/截断旧行为。截取处是正在说话的片段，短样例本身不能支撑完整语音质量结论。

证据文件：
- `environment-before.txt`、`current-constraints.txt`：原环境快照/解析约束；
- `dependency-dry-run.log`、`dependency-preserve-dry-run.log`：组合解析与保持旧版本解析；
- `qwen-preserve-dry-run.log`、`funasr-preserve-dry-run.log`：独立解析失败说明；
- `whisper-settings.yaml`、`whisper.log`、`audio/sample.wav`、`whisper-existing/sample.{json,txt}`。

初始依赖命令的证据路径位于 tmp，随后归档到上述日志目录；未把音频或模型权重提交到 Git。

## 验证与自评

- `.venv/bin/python -m pytest`：基线 292 passed / 5.99 秒；新增本文档后复跑 292 passed / 5.52 秒，完整日志 `pytest-final.log`。
- `environment-before.txt` 与 `environment-after.txt` diff 无变化，原环境包版本未被替换；`pip check` 与 `git diff --check` 均通过。
- 真实项目阶段 2 脚本实际退出 0，完整消费 Whisper 推理结果；不是 mock。
- 按 `docs/REVIEW_CHECKLIST.md` 自评：范围内；使用项目 .venv；没有修改上游/历史任务或 JSON 结构；已检查真实样例；新候选关键目标未生效，有依赖版本选择与真实推理验收阻塞；**不能宣告整体完成或建议开始 Web 加厚**。
- 未改前端，因此未执行前端构建/类型检查；未安装新后端，未宣称新引擎可用。
- 没有人工对照稿，未计算 CER；未采集峰值显存或分离冷启动耗时，未给出“优于 Whisper”的结论。

## 初始下一步与完成条件（历史记录）

先解决环境版本决策，依次真实运行 Qwen 1.7B + ForcedAligner、Qwen 0.6B、Paraformer、Nano，记录实际时间戳、模型/SDK revision、冷启动/推理耗时与资源；8GB 显存是否足够加载 1.7B 和 aligner 必须实测，不能靠参数量推断。

全部穿刺通过后再封装 Whisper 等价入口、后端标准化/校验/安全发布、候选覆盖与任务快照、CLI/Web 选择及实际状态显示、GPU 子进程互斥和可选部署；按用户方案补自动测试与新增引擎长音频/静音/下游读取验收。接入结论和人工质量结论分开报告；没有人工稿不编造 CER。

---

## 续轮实现与验收（最新）

### 已实现的调用链与环境选择

CLI / Web 请求 `asr_candidate` → `ModelOverrides` → 独立任务 YAML（typed ASR 快照重新落盘）→ `02_transcribe` → `transcribe_batch` 注册表派发 → Whisper 原路径或选定 PyTorch worker → 验证 JSON/TXT 发布。任务 manifest 保存候选，状态优先读取实际产物 engine/model。候选列表 API 只检查必要包存在性，不下载模型、不假称 runtime/cache 已验收。

原 `.venv` 包版本完全未更改。新 SDK 共同安装并运行在 `.venv/asr-py312`（Python 3.12.13）；旧穿刺路径 `.venv/asr-spike-py312` 保留软链接。torch/torchaudio 2.8.0、qwen-asr 0.0.6、FunASR 1.3.0、Transformers 4.57.6、numpy 1.26.4、huggingface-hub 0.36.2。真实 CUDA runtime 12.8，不是驱动显示的 CUDA 13.1。依赖快照见 `requirements-asr-constraints.txt`，安装说明见 `docs/ASR_BACKENDS.md`。

缓存归档为 `~/.cache/transcript-pipeline/asr-models/{hf,ms}`；旧 `asr-spike` 路径保留软链接。隔离 worker 按阶段加载一次所选模型，阶段结束释放；不是独立服务平台。基础应用未安装新 SDK 时仍可启动和使用 Whisper。

- Qwen 固定上述两个 ASR commit 与 ForcedAligner commit，CUDA FP16 / CPU FP32、SDPA、batch=1。
- 原 HF `funasr/paraformer-zh` checkpoint 实测无 timestamps，不当作通过；改为明确命名的官方 SeACo `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch@v2.0.4`。权重 SHA256 `3d491689244ec5dfbf9170ef3827c358aa10f1f20e42a7c59e15e688647946d1`，运行时强校验；CPU ct-punc revision `d0e55e2b8722a78b63705ff443d09c4f86e5d750`。
- Nano 使用 wheel 中显式注册的实现、`trust_remote_code=False`，不下载/执行远程 Python；CUDA BF16 decoder / FP32 encoder，CPU FP32。原 FP16 穿刺触顶失败，未伪装成功。

### 风险驱动修正与护栏

1. 2 秒数字静音直接调用 SDK：两个 Qwen 输出“嗯。”、SeACo 也输出词语。公共入口现在先做 CPU Silero VAD，保留真实语音样本区间；无语音时空产物明确 `inference_performed=false`，不把文字幻觉当成功。正常语音但模型无文本明确失败。
2. 新后端按真实 VAD 区间最长 30 秒 PCM 切块，恢复绝对偏移、记录每块区间与硬切告警。没有按字符长度均分、自动补字或隐藏失败后换模型。Nano 元数据明确是 VAD 音频块，不冒充字/句级时间。
3. 195 秒 Qwen 官方长块可以通过，但 10 分钟样本的 0.6B 在较长 SDK 块上触及 2048 token。改为有界 VAD 子块后两个 Qwen 均通过；保留失败日志，不靠增大 token 上限掩盖循环。
4. ForcedAligner 有零时长字/词；个别零时长文字段只与相邻实际边界聚合，保留全文并告警。全部零时长仍失败，不补造时间。
5. Nano checkpoint 默认随机采样，VAD 子块实测触顶；只 greedy 仍有一次真实失败。最终明确 `do_sample=false, repetition_penalty=1.1`，同源 10 分钟真实运行通过。上限检查继续生效，参数进入 metadata。
6. Linux 工作区锁和 GPU 文件锁约束任务子进程；继承 fd 的进程锁保活测试通过。Whisper CUDA wheels 预加载只走旧分支，新 worker 不继承其 library dirs。不保证不同 project root/主机共用锁。
7. 发布前校验全文/segments/TXT、ID、有限时间、顺序、时长；临时写入、rename 和 OSError 回滚。没有声称 JSON/TXT 两次 rename 是掉电/SIGKILL 原子事务。
8. 历史重跑默认沿用任务候选与 profile；显式切换候选拒绝并要求新任务/独立文件工作区。typed/raw overrides 都落盘，不污染共享配置；两个任务快照和全局默认改变的回归测试通过。普通转录阶段也在 run 目录保存 `asr-settings.yaml`，阶段/文件阶段保存有效 config/profile/candidate 到重试 payload；重试不受后来的全局 ASR/profile 改变影响。

### 当前 UI 局部规格与验证

以下是已实现的局部关系，不是未来页面设计；单任务/批量不改原材料与输出操作。

```text
单任务 / 批量：材料区             运行参数区
┌─────────────────────┬─────────────────────────────┐
│ 原视频/录音、参考材料 │ ASR 候选 [Whisper ▼]  profile [▼] │
│ 原上传/输出操作      │ 依赖状态 ≠ 模型验证；新候选不继承 beam │
│                     │ 原 LLM backend / OCR 参数         │
└─────────────────────┴─────────────────────────────┘
设置页：默认 ASR [▼] 与原默认 backend/profile 共置，保存仅影响新任务。
阶段页：stage≠transcribe → 不显示 ASR；stage=transcribe → ASR [▼]
任务卡：保存候选；有产物时优先实际 engine/model，不借用当前全局默认。
```

候选菜单由已有 UI 库的 select 承载；依赖缺失/未知项禁用，显示原因性质。展开时不挤动宿主布局，菜单在视口内；关闭后原控件不跳动。桌面双栏、移动端纵向适配，不新增导航/复杂面板。浏览器实际切换、stage 可见性、菜单边界、选择前后布局和 390px 无横向溢出检查通过。截图环境缺少 CJK 字体，中文显示方框是本机浏览器字体问题；不能把截图当作中文视觉质量验收。

### 真实运行与证据

统一日志根：`data/output/logs/asr-spike-20260930/continuation/`（ignored，不提交音频/模型）。

- 初始短样例 25 秒，跨分块样例 195 秒；五候选公共 CLI + GPU 全部退出 0。最终另跑 2 秒语音/2 秒静音；新增四候选 CPU FP32 真实语音运行全部退出 0（最新 `final-cpu-vad-status.log`），不以纯静音跳过模型代替 CPU 验证。
- 同源 10 分钟对话样例从原录音 `[120,720]` 秒只读截取；`acceptance/<candidate>/representative-10m.{json,txt}` 各自独立。音频全部计时相对该输入文件，不是相对原视频 120 秒的全局起点。
- 五候选的四个输入（10 分钟、25 秒、2 秒语音、2 秒静音）各产生 JSON/TXT。检查全文一致、ID 唯一、有限/顺序/时长与 metadata。非空语音可被已有 `load_asr_payload/build_asr_blocks/load_text_file` 消费；静音空 TXT 被原 refinement 明确拒绝，未改阶段 6 或补造整理文。
- 10 分钟耗时表是 **模型转录耗时与 PyTorch 阶段累计分配峰值**，不是端到端 cold start、总进程 GPU 占用或 CER：

| 候选 | 文本段数 | 文本字符（含段间换行） | 推理秒 | PyTorch 分配峰值 MiB |
|---|---:|---:|---:|---:|
| Whisper existing | 415 | 2824 | 未分离采集 | 未采集 |
| Qwen 1.7B | 149 | 3034 | 74.45 | 5889 |
| Qwen 0.6B | 164 | 3052 | 81.87 | 3496 |
| SeACo Paraformer | 74 | 2809 | 13.56 | 1061 |
| Nano | 22 | 2598 | 68.42 | 2093 |

加载耗时、实际分块、精度、版本、告警另见每份 metadata。文本字数/段数不能当准确性排名。逐份抽查开头、中间和结尾，候选之间错词/分块差异明显；Nano 出现 `[breath]` 与需回听的疑似偏题内容。没有人工稿或听音对照，不计算 CER，不宣布最好模型。当前样本主要是对话，尚不代表原文朗读+讲解+问答全覆盖。

- 使用隔离 `web-root` 的真实 localhost 服务，未碰运行中的应用任务：五候选均完成上传 → `/api/stages/transcribe/file-run` → 状态 success → ZIP 下载，归档只有 JSON/TXT；最终 `web-asr-final-check.log` 与 `web-asr-results.json` 记录每个 run_id 与身份。
- 前端 typecheck/build 和真实浏览器交互通过；构建保留原 bundle >500KB warning。`ui-final-check.log`、`*-asr-open.png`、`*-asr-selected.png` 为本地证据。
- 模型穿刺 raw SDK、失败日志、实际 CLI/API 验收和常规单元测试分开存档，不把 mock 当真实接入。

### 修改落点与边界

新增 `src/asr/{registry,segmentation,qwen3_backend,funasr_backend,worker}.py`；保留 `src/asr_utils.py` 入口与 Whisper 解码路径。扩展 schemas/settings overrides/job runner、5 个 CLI、API/Web requests/tasks/frontend settings，以及复用 `AsrCandidateSelector.vue` 的 4 页和任务卡。新增 probe 脚本、可选 requirements/constraints、Docker build arg 和 ASR 使用文档；新增 probe/backend 回归测试。

没有 OCR、LLM 校对、阶段 6、导出格式、embedding、全局复杂对齐、自动投票/改默认、历史全量重跑或常驻模型服务改造。没有 commit/push/关闭 issue，也未重启现有 Docker 服务。

### 自评与剩余验收

按 `docs/REVIEW_CHECKLIST.md`：批准范围内；项目 `.venv` pytest 与真实脚本；上游/历史数据未回改；JSON 主结构保持、新 metadata 向后兼容；实际短/长/静音与下游读取已检查。原 `.venv` freeze 与初始快照无差异，两套环境 pip check 均通过。

常规 pytest 当前 **341 passed / 8.00 秒**；包括注册表/非法候选、配置到任务 YAML、双任务独立性、历史重跑冻结、字符对齐/零时长聚合、VAD 真区间、原产物保护、发布回滚和 GPU fd 保活。它们不下载大模型。全量日志 `pytest-final.log`；`git diff --check` 通过。

Docker 默认仍只安装基础 Whisper；可选 `ASR_BACKENDS=all` 隔离环境构建经历代理 JSON 截断、887MB torch wheel 下载中断引起的哈希拒绝（未禁用验证）。改用固定 pip 26.2.1 支持断点续传、固定 PyPI 索引直连与 HTTP 下载代理后，可选镜像已成功构建（`docker-build-resumable.log`，image `db571b31dd88`）；原环境与 SDK 两层 pip check 通过。这份日志仅是初次构建证明，不把宿主推理等同容器验收。

随后临时容器真实转录暴露基础环境的 PyAV 19 删除 `av.open(metadata_errors=...)`，导致 Whisper 失败。Docker 最终单独固定基础 decoder `av==16.1.0`（worker 保留独立版本），没有更换模型、改解码参数或忽略错误。固定 pip 的 optional SDK 安装层与原基础应用环境隔离；重新构建最新源码后，临时容器真实 GPU 矩阵运算和**五候选分别对 2 秒语音 + 2 秒静音**全部通过，两套 pip check 通过。

最终镜像：`transcript-pipeline:asr-acceptance`，image ID `sha256:28b0e449ad78c1add2a908d7cad342edc14301d0485b30d14da702bf78b10c7b`。完整日志 `docker-build-verified.log`、`docker-inference-final.log`，输出 `continuation/docker-asr-data/asr-<candidate>/*.{json,txt}`，检查候选身份、device=cuda、非空语音/空静音及 JSON/TXT 一致。没有将此临时镜像部署到现有服务，也没有把短语音容器验收称作容器长录音质量验收。临时 Web 服务已停止，没有留下占用 GPU 的验收任务。

**当前结论：接入实现与本轮工程验收通过，人工识别质量验收未完成。** 下一步提供朗读/讲解/问答的 10–20 分钟样本及人工稿，复核错词、硬切边界、Nano 疑似偏题片段和 ForcedAligner 零时长项；若要迁移服务，再单独批准部署和实际任务长录音验证。保持 Whisper 默认，不因本轮有限样本自动换模型。
