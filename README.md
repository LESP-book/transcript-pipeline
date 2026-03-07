# transcript-pipeline

一个用于处理读书会录屏的自动化项目。

目标是把录屏中的语音自动整理成适合人工校对的 Markdown 文稿，并尽量区分以下三类内容：

1. 原文朗读
2. 讲解内容
3. 提问 / 讨论 / 问答环节

本项目采用“两层输出”设计：

- `review.json`：结构化中间结果，便于调试、排错、后续再加工
- `final.md`：最终给人工校对使用的 Markdown 文稿

---

## 一、项目目标

输入：

- 录屏视频或音频
- 电子版原文链接 / 文本 / PDF（可选）
- 模型校对提示词

输出：

- 一份整理好的 Markdown 文稿：
  - 原文朗读部分用 Markdown 引用格式 `>`
  - 讲解部分用普通段落
  - 提问部分单独放入 `## 提问环节`

要求：

- 添加标点
- 修改明显错字、别字、同音误识别
- 合理分段
- 不改变原意
- 不擅自增删观点
- 不把讲解改写成论文语言
- 不显示时间戳
- 不显示参考原文
- 不显示内部判断信息

---

## 二、开发与运行环境

### 开发环境
当前开发机：

- Ubuntu 24
- 无 NVIDIA GPU
- 以 CPU 模式开发和调试

### 目标运行环境
后续迁移机：

- Windows + WSL2
- NVIDIA 3060Ti
- 可使用 CUDA 加速 ASR

### 环境设计原则

必须从第一天开始就支持“本机开发、异机迁移”：

- 主流程代码不写死 CPU / CUDA
- 路径不写死为某一台机器
- 模型、设备、缓存目录都通过配置文件控制
- 本地开发与 WSL2 GPU 运行共用同一套代码
- 通过 `settings.yaml` 切换运行后端

---

## 三、项目范围

### 第一阶段（先实现）
1. 读取 `data/input/videos/` 下的视频文件
2. 用 ffmpeg 抽取音频
3. 调用 ASR 引擎转录
4. 读取参考原文（txt / md / 可复制 PDF / OCR 后 PDF）
5. 对转录文本进行分段
6. 初步区分：
   - quote（原文朗读）
   - lecture（讲解）
   - qa（提问 / 讨论）
7. 调用 LLM 进行校订
8. 生成：
   - `review.json`
   - `final.md`

### 第二阶段（后实现）
1. 支持 WhisperX
2. 支持更强的对齐策略
3. 支持批量任务
4. 支持多种 LLM 提供方
5. 支持 docx / txt / html 导出

### 暂不实现
1. GUI 自动点击 Buzz
2. 浏览器复制粘贴聊天框式处理
3. Docker 强依赖
4. 一上来就做复杂桌面 agent

---

## 四、推荐技术路线

### 主流程
- Python 3.12
- 配置驱动
- 命令行运行
- 中间结果可追踪

### 外部工具
- ffmpeg：抽取音频
- OCRmyPDF：扫描 PDF OCR
- poppler / PyMuPDF / pdfplumber：提取 PDF 文本

### ASR
第一版优先：

- faster-whisper

后续可选：

- WhisperX

### LLM
第一版先保留抽象接口，支持未来切换：

- OpenAI / GPT-5.4
- Gemini

---

## 五、目录结构

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
│   ├── 04_segment.py
│   ├── 05_correct.py
│   ├── 06_export.py
│   └── run_pipeline.py
├── src/
│   ├── __init__.py
│   ├── config_loader.py
│   ├── runtime_utils.py
│   ├── ffmpeg_utils.py
│   ├── asr_utils.py
│   ├── pdf_utils.py
│   ├── segment_utils.py
│   ├── llm_utils.py
│   ├── export_utils.py
│   └── schemas.py
└── tests/
    ├── test_config.py
    ├── test_extract_audio.py
    └── test_export.py
