# classify_and_correct

你现在要把一篇中文读书会录音转写稿直接整理成最终 Markdown 文稿。

你必须完成这些任务：
1. 为全文添加合理标点。
2. 修正明显错字、别字、同音误识别。
3. 做合理分段，提高可读性。
4. 严格保留原意，不得扩写、缩写、总结、改写观点。

这是一篇读书会内容，通常同时包含：
- 原文朗读
- 讲解
- 串场或开场说明
- 末尾的提问、回答、讨论

整理要求：
1. 明显属于原文朗读的部分，优先参考提供的原文校对，并使用 Markdown 引用格式 `>`。
2. 讲解、串场、导语使用普通段落。
3. 如果后面出现提问、回答、讨论内容，请整理到 `## 提问环节` 下。
4. 讲解部分只修正明显错字、标点和断句，保持讲话风格，不要改成论文语言。
5. 不要显示时间戳。
6. 不要显示参考原文。
7. 不要显示任何内部判断信息、分类信息、校对说明或注释。

如果参考原文为空或不足，请仅基于录音转写文本做保守整理，不要编造原文。

请只返回 JSON，不要输出解释，不要重复任务要求。

JSON 顶层必须包含这些字段：
- final_markdown: string
- refinement_strategy: string
- refinement_reason: string
- needs_review_sections: array
- refinement_notes: array

字段要求：
- `final_markdown` 直接放最终 Markdown 文稿。
- `needs_review_sections` 只列出你确实拿不准、建议人工复核的片段，每项至少包含 `excerpt` 和 `reason`。
- `refinement_notes` 只写简短说明，不要冗长。
