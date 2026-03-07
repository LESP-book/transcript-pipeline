# transcript-pipeline

中文读书会录屏整理流水线。

这个项目的目标是把录屏中的语音内容整理为适合人工校对的 Markdown 文稿。整体设计从一开始就考虑两种运行环境：

- Ubuntu 24 本地开发环境，CPU 运行
- Windows + WSL2 + NVIDIA 3060Ti 环境，后续可切换到 GPU 后端

当前仓库只实现第一阶段，不包含 ASR、OCR、PDF 文本提取、LLM 调用、内容分类或最终 Markdown 拼装。

## 当前阶段已实现

- 项目目录骨架
- `config/settings.yaml` 配置读取
- `local_cpu` / `wsl2_gpu` profile 机制
- 扫描 `data/input/videos/` 下的视频文件
- 使用 `ffmpeg` 抽取为 `wav`、单声道、16000 Hz 音频
- 两个最小 CLI 入口
- 最基本单元测试

## 当前阶段未实现

- ASR 转录
- OCR
- 参考原文解析
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
│   └── run_pipeline.py
├── src/
│   ├── __init__.py
│   ├── config_loader.py
│   ├── runtime_utils.py
│   ├── ffmpeg_utils.py
│   └── schemas.py
└── tests/
    ├── test_config.py
    └── test_extract_audio.py
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
python -m venv .venv
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
python scripts/01_extract_audio.py
```

指定 profile：

```bash
python scripts/01_extract_audio.py --profile local_cpu
```

通过统一入口运行当前唯一已实现阶段：

```bash
python scripts/run_pipeline.py --stage extract-audio
```

运行测试：

```bash
pytest
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

## 下一阶段建议

下一步最适合优先做的事情是引入 ASR 抽象层与第一版转录阶段：

- 保持 `local_cpu` / `wsl2_gpu` profile 复用
- 定义统一转录接口，不把后端写死
- 先输出中间 ASR 结果，不急着做分类和最终文稿拼装
