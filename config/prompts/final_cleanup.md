# final_cleanup

你当前处于阶段 6 的“整篇单次校对与 Markdown 整理”步骤。

输入中会同时提供：

- `整篇参考原文`
- `预替换全文`

`预替换全文` 内部含两类片段：

- `locked_quote`
  - 这些片段已经通过规则高置信替换为参考原文
  - 你不得改写其实词内容
  - 只允许调整标点、断句、空行与 Markdown 引用格式
- `unlocked_text`
  - 这些片段尚未锁定
  - 你可以结合整篇参考原文继续修复明显错字、同音误识别和遗漏的原文段
  - 但如果证据不足，不得把讲解误改成原文

你的职责：
1. 保持 `locked_quote` 的实质内容不变。
2. 在 `unlocked_text` 中谨慎修正明显错误。
3. 将明显属于原文朗读的段落整理为 `>` 引用格式。
4. 将明显属于提问、回答、讨论的内容整理到 `## 提问环节` 下。
5. 讲解、串场、导语保留为普通段落。
6. 输出最终 Markdown。

绝对禁止：
1. 改写 `locked_quote` 的实词内容。
2. 在证据不足时把讲解强行改写成原文。
3. 总结、概括、压缩内容。
4. 合并多段内容为抽象表述。
5. 补充原文中没有的信息。
6. 输出内部判断说明或内部标签。

处理原则：
1. 如果结构判断拿不准，优先保留原顺序与原文措辞。
2. 不要显示时间戳。
3. 不要在最终输出中显示参考原文。
4. 最终输出统一使用简体中文。
5. 最终输出中不得保留 `locked_quote`、`unlocked_text`、`[SEGMENT xx]` 等内部标记。

请只返回 JSON，不要输出解释。

JSON 顶层必须包含这些字段：
- final_markdown: string
- section_map: array
- refinement_notes: array
- needs_review_sections: array

字段要求：
- `final_markdown` 直接放最终 Markdown 文稿。
- `section_map` 记录主要结构分区及其来源块。
- `refinement_notes` 只写简短说明，不要冗长。
- `needs_review_sections` 只列出你确实拿不准、建议人工复核的片段，每项至少包含 `excerpt` 和 `reason`。
