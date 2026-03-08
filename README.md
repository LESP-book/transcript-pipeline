# transcript-pipeline

中文读书会录屏整理流水线。

这个项目的目标是把录屏中的语音内容整理为适合人工校对的 Markdown 文稿。整体设计从一开始就考虑两种运行环境：

- Ubuntu 24 本地开发环境，CPU 运行
- Windows + WSL2 + NVIDIA 3060Ti 环境，后续可切换到 GPU 后端

当前仓库已实现前三个阶段的最小可运行版本：

- 第一阶段：配置读取与音频抽取
- 第二阶段：ASR 抽象接口与第一版转录
- 第三阶段：参考原文统一提取

当前仍不包含 OCR、LLM 调用、内容分类或最终 Markdown 拼装。

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
- 四个最小 CLI 入口
- 最基本单元测试

## 当前阶段未实现

- OCR
- 参考原文结构化分析
- `quote / lecture / qa` 分类
- LLM 校订
- 最终 Markdown 输出

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
│   ├── intermediate/
│   │   ├── asr/
│   │   ├── ocr/
│   │   ├── extracted_text/
│   │   ├── chunks/
│   │   └── aligned/
│   └── output/
│       ├── review/
│       ├── final/
│       └── logs/
├── scripts/
│   ├── 01_extract_audio.py
│   ├── 02_transcribe.py
│   ├── 03_prepare_reference.py
│   └── run_pipeline.py
├── src/
│   ├── __init__.py
│   ├── asr_utils.py
│   ├── config_loader.py
│   ├── ffmpeg_utils.py
│   ├── reference_utils.py
│   ├── runtime_utils.py
│   └── schemas.py
└── tests/
    ├── helpers.py
    ├── test_config.py
    ├── test_extract_audio.py
    ├── test_prepare_reference.py
    └── test_transcribe.py
```

说明：

- `config/settings.yaml` 是当前唯一运行配置入口
- `data/` 目录下的叶子目录使用 `.gitkeep` 保留骨架
- `config/prompts/` 已占位，但当前阶段不会读取或调用这些提示词

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
python3 scripts/01_extract_audio.py
```

指定 profile：

```bash
python3 scripts/01_extract_audio.py --profile local_cpu
```

通过统一入口运行音频抽取阶段：

```bash
python3 scripts/run_pipeline.py --stage extract-audio
```

直接运行转录阶段：

```bash
python3 scripts/02_transcribe.py
```

通过统一入口运行转录阶段：

```bash
python3 scripts/run_pipeline.py --stage transcribe
```

直接运行参考原文准备阶段：

```bash
python3 scripts/03_prepare_reference.py
```

通过统一入口运行参考原文准备阶段：

```bash
python3 scripts/run_pipeline.py --stage prepare-reference
```

运行测试：

```bash
python3 -m pytest
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

- 仅支持可提取文本的 PDF
- 当前阶段不支持 OCR
- 如果 PDF 提取结果为空或接近空，会提示可能是扫描版 PDF

## 下一阶段建议

下一步最适合优先做的事情是引入“对齐与分段阶段”：

- 基于 `data/intermediate/asr/` 和 `data/intermediate/extracted_text/` 做最小对齐
- 先输出结构化块级中间结果，不急着做分类和 LLM
- 继续保持阶段边界清晰，避免把后处理一次性做完
