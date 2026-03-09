# transcript-pipeline

中文读书会录屏整理流水线。

这个项目的目标是把录屏中的语音内容整理为适合人工校对的 Markdown 文稿。整体设计从一开始就考虑两种运行环境：

- Ubuntu 24 本地开发环境，CPU 运行
- Windows + WSL2 + NVIDIA 3060Ti 环境，后续可切换到 GPU 后端

当前仓库已实现前八个阶段的最小可运行版本：

- 第一阶段：配置读取与音频抽取
- 第二阶段：ASR 抽象接口与第一版转录
- 第三阶段：参考原文统一提取
- 第四阶段：块级对齐与分段增强版（保留为辅助调试链路）
- 第五阶段：块级内容候选分类（保留为辅助调试链路）
- 第六阶段：本地 CLI 模型整篇整理，直接读取 `asr.txt + reference.txt` 产出最终 Markdown 草稿（`codex` / `gemini`，含保守降级后端）
- 第七阶段：将阶段 6 的 Markdown 结果写入最终输出目录
- 第八阶段：单任务 job 入口，支持显式指定视频、参考源和输出目录

当前仍不包含 OCR、最终分类定稿或自动发布能力。

## 当前阶段已实现

- 项目目录骨架
- `config/settings.yaml` 配置读取
- `local_cpu` / `wsl2_gpu` profile 机制
- 扫描 `data/input/videos/` 下的视频文件
- 使用 `ffmpeg` 抽取为 `wav`、单声道、16000 Hz 音频
- 扫描 `data/input/audio/` 下的音频文件
- 使用 `faster-whisper` 生成转录中间结果
- 输出 `data/intermediate/asr/` 下的 JSON 和 TXT
- 扫描 `data/input/reference/` 下的参考原文文件
- 支持 `.txt` / `.md` / 可提取文本的 `.pdf`
- 输出 `data/intermediate/extracted_text/` 下的 JSON 和 TXT
- 读取 ASR 与参考文本中间结果并生成 `data/intermediate/aligned/` 对齐结果
- 对齐阶段支持更细粒度分段、文本 normalization 和 top-k 匹配候选
- 基于 aligned 结果输出保守的候选分类到 `data/intermediate/classified/`（可选辅助）
- 基于 `asr.txt + extracted_text.txt + 提示词` 直接输出整篇 Markdown 草稿到 `data/intermediate/refined/`
- 阶段 6 支持本地 `codex` 与 `gemini` CLI 双后端整篇比较后生成单一 `final_markdown`
- 阶段 7 将阶段 6 的 `final_markdown` 写入 `data/output/final/`
- 九个最小 CLI 入口
- 最基本单元测试

## 当前阶段未实现

- OCR
- 参考原文结构化分析
- 复杂对齐路径搜索
- 最终分类定稿
- `quote / lecture / qa` 分类
- docx / html 等其他导出格式

## 目录结构

```text
transcript-pipeline/
├── README.md
├── .gitignore
├── .env.example
├── requirements.txt
├── config/
│   ├── settings.yaml
│   └── prompts/
│       ├── classify_and_correct.md
│       └── final_cleanup.md
├── data/
│   ├── input/
│   │   ├── videos/
│   │   ├── audio/
│   │   └── reference/
│   ├── jobs/
│   ├── intermediate/
│   │   ├── asr/
│   │   ├── ocr/
│   │   ├── extracted_text/
│   │   ├── chunks/
│   │   ├── aligned/
│   │   ├── classified/
│   │   └── refined/
│   └── output/
│       ├── review/
│       ├── final/
│       └── logs/
├── scripts/
│   ├── 00_run_main_pipeline.py
│   ├── 01_extract_audio.py
│   ├── 02_transcribe.py
│   ├── 03_prepare_reference.py
│   ├── 04_align.py
│   ├── 05_classify.py
│   ├── 06_refine.py
│   ├── 07_export_markdown.py
│   ├── 08_run_job.py
│   └── run_pipeline.py
├── src/
│   ├── __init__.py
│   ├── align_utils.py
│   ├── asr_utils.py
│   ├── classify_utils.py
│   ├── config_loader.py
│   ├── ffmpeg_utils.py
│   ├── job_runner.py
│   ├── refine_utils.py
│   ├── reference_utils.py
│   ├── runtime_utils.py
│   └── schemas.py
└── tests/
    ├── helpers.py
    ├── test_config.py
    ├── test_extract_audio.py
    ├── test_align.py
    ├── test_classify.py
    ├── test_export_markdown.py
    ├── test_refine.py
    ├── test_job_runner.py
    ├── test_prepare_reference.py
    └── test_transcribe.py
```

说明：

- `config/settings.yaml` 是当前唯一运行配置入口
- `data/` 目录下的叶子目录使用 `.gitkeep` 保留骨架
- 第六阶段会读取 `config/prompts/classify_and_correct.md`
- 第七阶段会直接写出 `data/intermediate/refined/*.json` 中的 `final_markdown`

## 运行要求

1. Python 3.12
2. 系统已安装 `ffmpeg`

安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

默认配置文件为 `config/settings.yaml`。

当前支持两个 profile：

- `local_cpu`
- `wsl2_gpu`

可以通过以下方式切换：

- 配置文件中的 `runtime.profile`
- 环境变量 `TRANSCRIPT_PROFILE`
- CLI 参数 `--profile`

优先级从高到低依次为：CLI 参数、环境变量、配置文件默认值。

## 运行方式

直接运行音频抽取：

```bash
.venv/bin/python scripts/01_extract_audio.py
```

指定 profile：

```bash
.venv/bin/python scripts/01_extract_audio.py --profile local_cpu
```

通过统一入口运行音频抽取阶段：

```bash
.venv/bin/python scripts/run_pipeline.py --stage extract-audio
```

直接运行转录阶段：

```bash
.venv/bin/python scripts/02_transcribe.py
```

通过统一入口运行转录阶段：

```bash
.venv/bin/python scripts/run_pipeline.py --stage transcribe
```

直接运行参考原文准备阶段：

```bash
.venv/bin/python scripts/03_prepare_reference.py
```

通过统一入口运行参考原文准备阶段：

```bash
.venv/bin/python scripts/run_pipeline.py --stage prepare-reference
```

直接运行对齐阶段：

```bash
.venv/bin/python scripts/04_align.py
```

通过统一入口运行对齐阶段：

```bash
.venv/bin/python scripts/run_pipeline.py --stage align
```

直接运行候选分类阶段：

```bash
.venv/bin/python scripts/05_classify.py
```

通过统一入口运行候选分类阶段：

```bash
.venv/bin/python scripts/run_pipeline.py --stage classify
```

直接运行阶段 6 精修：

```bash
.venv/bin/python scripts/06_refine.py
```

通过统一入口运行阶段 6：

```bash
.venv/bin/python scripts/run_pipeline.py --stage refine
```

阶段 6 说明：

- 默认使用本机 `codex` 与 `gemini` CLI 作为整篇整理后端
- 主输入是 `data/intermediate/asr/*.txt` 和同 basename 的 `data/intermediate/extracted_text/*.txt`
- 不再依赖 `classified.json` 作为阶段 6 的主输入
- 提示词贴近网页端单轮整理模式，直接要求输出最终 Markdown
- 对同一份整篇文本会比较两个后端结果，再输出单一 `final_markdown`
- `final_markdown` 已直接包含：
  - 原文朗读引用块 `>`
  - 讲解普通段落
  - `## 提问环节`
- 如果两个后端都失败，会回退到本地保守整理逻辑

直接运行阶段 7 写入最终 Markdown：

```bash
.venv/bin/python scripts/07_export_markdown.py
```

通过统一入口运行阶段 7：

```bash
.venv/bin/python scripts/run_pipeline.py --stage export-markdown
```

阶段 7 说明：

- 输入为 `data/intermediate/refined/*.json`
- 输出为 `data/output/final/*.md`
- 当前生成的是最终 Markdown 校对稿，供人工最后通读和少量修字
- 阶段 7 只负责把阶段 6 已生成的 `final_markdown` 落盘
- 不再负责正文结构重组

当前推荐主链：

- `extract-audio`
- `transcribe`
- `prepare-reference`
- `refine`
- `export-markdown`

`align` / `classify` 当前保留为辅助调试链路，不再是默认成稿主链。
默认整链运行时，应优先按以上五个阶段串行执行，而不是把 `align` / `classify` 作为必经步骤。

一键运行当前推荐主链：

```bash
.venv/bin/python scripts/00_run_main_pipeline.py
```

推荐的单任务运行方式：

```bash
.venv/bin/python scripts/08_run_job.py \
  --video "/path/to/video.mp4" \
  --reference "/path/to/reference.pdf" \
  --output-dir "/path/to/output"
```

可选附加术语词表：

```bash
.venv/bin/python scripts/08_run_job.py \
  --video "/path/to/video.mp4" \
  --reference "/path/to/reference.pdf" \
  --book-name "家庭、私有制和国家的起源" \
  --chapter "第八章" \
  --glossary-file "/path/to/chapter_terms.txt" \
  --output-dir "/path/to/output"
```

单任务入口说明：

- 不再要求视频文件和参考文件同 basename
- 每次运行都会创建独立的 `data/jobs/<job_id>/`
- 参考源支持：
  - 本地 `txt`
  - 本地 `md`
  - 本地 `pdf`
  - 公开网页链接
- 网页链接若目标是 PDF，会先下载 PDF，再按阶段 3 处理
- 最终 Markdown 会额外复制到 `--output-dir`
- `config/glossaries/marxism_common.txt` 会默认参与构造本次任务的 `asr.initial_prompt`
- `--book-name`、`--chapter`、`--glossary-file` 会追加到本次任务的 `initial_prompt`
- 附加词表文件格式为一行一个词条

运行测试：

```bash
.venv/bin/python -m pytest
```

## 音频抽取行为

- 扫描目录：`data/input/videos/`
- 支持扩展名：`.mp4`、`.mkv`、`.mov`、`.webm`
- 输出目录：`data/input/audio/`
- 输出格式：`wav`
- 声道数：单声道
- 采样率：16000 Hz
- 默认不覆盖已有输出，只有在配置中 `audio.overwrite: true` 时才覆盖

如果出现以下情况会给出明确错误：

- `ffmpeg` 不存在
- 输入目录不存在或没有可处理视频
- 配置文件不存在或 profile 无效

## 转录行为

- 扫描目录：`data/input/audio/`
- 支持扩展名：`.wav`、`.mp3`、`.m4a`、`.flac`
- 使用 `faster-whisper`
- 从 profile 读取 `device`、`asr_compute_type`、`asr_model_size`
- 输出目录：`data/intermediate/asr/`
- 每个音频输出：
  - `<basename>.json`
  - `<basename>.txt`

JSON 中间结果至少包含：

- `source_file`
- `engine`
- `model_size`
- `device`
- `compute_type`
- `language`
- `segments`
- `full_text`

如果出现以下情况会给出明确错误：

- 未安装 `faster-whisper`
- `device` 配置无效
- `cuda` profile 不能正常初始化
- 音频目录为空

## 参考原文准备行为

- 扫描目录：`data/input/reference/`
- 当前仅处理顶层文件，不递归子目录
- 支持扩展名：`.txt`、`.md`、`.pdf`
- 输出目录：`data/intermediate/extracted_text/`
- 每个参考文件输出：
  - `<basename>.txt`
  - `<basename>.json`

JSON 中间结果至少包含：

- `source_file`
- `source_type`
- `output_text_file`
- `extraction_method`
- `success`
- `text_length`
- `warnings`

PDF 支持边界：

- 当前 PDF 默认优先尝试 `gemini` CLI OCR
- 如果 Gemini OCR 失败，但 PDF 自带文字层可提取，则回退到文字层提取
- 如果 Gemini OCR 失败，且文字层为空或接近空，并且 `reference.run_ocr_when_needed = true`，会回退到 `ocrmypdf + tesseract`
- 当前 OCR 路线面向中文扫描版 PDF
- 如果 OCR 结果仍为空或接近空，会提示当前 PDF 质量可能较差

## 对齐与分段行为

- 读取目录：`data/intermediate/asr/` 与 `data/intermediate/extracted_text/`
- 当前只处理同 basename 可配对的文件
- ASR 分段：按相邻 segments 保守合并，受最小/最大字符数和时长阈值控制
- reference 分段：优先按空行切段，再按句号、问号、叹号、分号等细分
- 匹配前会做轻量 normalization：
  - 统一空白
  - 统一全角半角
  - 统一常见分隔符与标点差异
- 对齐方法：基于 `rapidfuzz` 的轻量组合评分
- 输出目录：`data/intermediate/aligned/`
- 每个配对文件输出：
  - `<basename>.json`

aligned JSON 至少包含：

- `source_asr_file`
- `source_reference_file`
- `alignment_method`
- `total_asr_blocks`
- `total_reference_blocks`
- `blocks`

每个 `block` 现在至少包含：

- `block_id`
- `source_segment_ids`
- `start`
- `end`
- `asr_text`
- `matched_reference_text`
- `match_score`
- `match_status`
- `top_matches`

当前能力边界：

- 仍然只是块级对齐增强版
- 不做一对多 / 多对一复杂对齐
- 不做全局最优路径搜索
- 不做分类
- 不做 LLM 校对

## 候选分类行为

- 读取目录：`data/intermediate/aligned/`
- 输出目录：`data/intermediate/classified/`
- 当前只做候选分类，不做最终定稿
- 当前输出标签包括：
  - `quote_candidate`
  - `mixed_candidate`
  - `lecture_candidate`
  - `qa_candidate`
  - `intro_candidate`

分类主要依据：

- `match_score`
- `match_status`
- top-1 与 top-2 的分差
- 问答关键词
- 讲解口语标记
- 开场播报关键词

每个 `classified_block` 至少包含：

- `block_id`
- `start`
- `end`
- `asr_text`
- `matched_reference_text`
- `match_score`
- `match_status`
- `top_matches`
- `classification`
- `classification_reason`
- `confidence`

当前能力边界：

- 这只是候选分类层，不是最终分类结果
- 不做 LLM 校对
- 不做最终 Markdown 拼装

## 下一阶段建议

下一步最适合优先做的事情是引入“LLM 校对精修阶段”：

- 基于 `data/intermediate/classified/` 的候选分类结果做保守精修
- 先只处理文本校对和分类确认，不急着做最终 Markdown 拼装
- 继续保持中间结果可追踪，避免一步到位变成黑箱
