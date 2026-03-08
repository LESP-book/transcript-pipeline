````markdown
# PIPELINE_PLAN.md

本文件定义项目的阶段路线图。
Codex 在执行“进入下一阶段”类任务时，应首先参考本文件。

---

## 项目名称

读书会录屏整理流水线

---

## 项目目标

把读书会录屏中的语音内容整理为适合人工校对和后续发布的结构化文本。

材料可能同时包含：

- 原文朗读
- 讲解内容
- 提问 / 讨论 / 回答
- 开场播报、标题、年月、来源说明

---

## 总体处理链路

text
录屏视频 / 音频
→ 音频抽取
→ ASR 转录
→ 参考原文提取
→ 整篇最终 Markdown 整理
→ 最终整理稿导出

当前推荐的辅助调试链路：

text
录屏视频 / 音频
→ 音频抽取
→ ASR 转录
→ 参考原文提取
→ 块级对齐
→ 块级候选分类
→ LLM 校对精修
→ 最终整理稿导出


---

## 阶段 1：配置读取 + 音频抽取

### 目标

* 读取配置文件
* 扫描输入视频
* 用 ffmpeg 抽取音频
* 输出统一 wav

### 输入

* `data/input/videos/`

### 输出

* `data/input/audio/`

### 状态

* [x] 已完成

---

## 阶段 2：ASR 转录

### 目标

* 读取音频
* 调用 ASR 引擎
* 输出结构化转录 JSON 和纯文本 TXT

### 输入

* `data/input/audio/`

### 输出

* `data/intermediate/asr/*.json`
* `data/intermediate/asr/*.txt`

### 状态

* [x] 已完成

---

## 阶段 3：参考原文提取

### 目标

* 扫描参考原文文件
* 支持 txt / md / 可提取文本 PDF
* 统一提取为纯文本

### 输入

* `data/input/reference/`

### 输出

* `data/intermediate/extracted_text/*.json`
* `data/intermediate/extracted_text/*.txt`

### 当前边界

* 不支持 OCR
* 不做章节分析
* 不做语义处理

### 状态

* [x] 已完成

---

## 阶段 4：块级对齐（增强版）

### 目标

* 基于 ASR 与参考原文做块级对齐
* reference 细分到句级 / 短句群级
* 输出可追踪的对齐结果

### 输入

* `data/intermediate/asr/*.json`
* `data/intermediate/extracted_text/*.txt`

### 输出

* `data/intermediate/aligned/*.json`

### 关键字段

* `asr_text`
* `matched_reference_text`
* `match_score`
* `match_status`
* `top_matches`

### 当前边界

* 不做 OCR
* 不做 embedding 检索
* 不做全局最优路径
* 不做分类
* 不做 LLM 校对

### 状态

* [x] 已完成

---

## 阶段 5：块级候选分类

### 目标

* 基于 aligned 结果，对 block 做保守候选分类
* 为后续 LLM 精修提供安全中间层

### 输入

* `data/intermediate/aligned/*.json`

### 输出

* `data/intermediate/classified/*.json`

### 当前分类标签

* `quote_candidate`
* `mixed_candidate`
* `lecture_candidate`
* `qa_candidate`
* `intro_candidate`

### 当前原则

* 不追求最终定性
* 优先保守
* 避免把明显原文块误判成 lecture

### 状态

* [x] 已完成（规则修正版后可作为下一阶段输入）

---

## 阶段 6：LLM 校对精修

### 目标

直接基于整篇 ASR 文本与整篇参考原文，输出最终 Markdown 草稿。

### 输入

* `data/intermediate/asr/*.txt`
* `data/intermediate/extracted_text/*.txt`

### 预期输出

* `data/intermediate/refined/*.json`
* 主字段：`final_markdown`

### 处理原则

* 添加标点
* 修改明显错字、别字、同音误识别
* 合理分段
* 严格保留原意，不扩写、不总结
* 原文朗读部分使用 Markdown 引用格式 `>`
* 讲解、串场、导语使用普通段落
* 提问、回答、讨论内容整理到 `## 提问环节`
* 不显示时间戳
* 不显示参考原文
* 不显示内部判断信息

### 当前边界

* 不做 docx 导出
* 不做 OCR
* 不做新一轮 ASR
* 不做自动发布

### 状态

* [x] 已完成（当前推荐主流程）

---

## 阶段 7：最终整理稿导出

### 目标

将阶段 6 已生成的 `final_markdown` 写入最终输出目录。

### 预期格式

优先 Markdown 落盘，不再重组正文结构。

### 输入

* `data/intermediate/refined/*.json`

### 输出

* `data/output/final/*.md`

### 当前边界

* 不追求自动发布
* 不直接替代人工终审

### 状态

* [x] 已完成

---

## 未来可选增强（暂不进入）

这些内容只能在用户明确批准后再做：

1. OCR 支持
2. WhisperX / 更强 ASR 后端
3. 更复杂对齐策略
4. docx / html 导出
5. 规则 + LLM 联合拆分混合块
6. 多 agent / 自动化流水线封装
7. 非交互批处理脚本

### 状态

* [ ] 未批准

---

## 当前推荐推进顺序

当前推荐主链：

**阶段 1 → 阶段 2 → 阶段 3 → 阶段 6 → 阶段 7**

理由：

* 这条链路最贴近人工网页端已经验证有效的工作方式
* 简化后速度、稳定性和产出质量更平衡
* `align` / `classify` 仍保留为辅助调试链路
* 主流程不再依赖复杂的块级结构
* 默认整链运行时，不再要求经过 `align` / `classify`

---

## 阶段推进规则

进入下一阶段前，必须满足：

1. 上一阶段已通过 `.venv/bin/python -m pytest`
2. 上一阶段已在真实样例上运行
3. 上一阶段输出没有明显阻塞问题
4. 已按 `docs/REVIEW_CHECKLIST.md` 完成评审

如果不满足，应优先：

* 小范围修复
* 规则修正
* 或重新验证

而不是硬推进。

