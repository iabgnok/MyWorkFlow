---
version: 1.0
name: hello_world
description: A basic test workflow
---

## Step 1: 读取本地文本
**Action**: `file_reader`
**Input**:
- file_path
**Output**:
- file_content

## Step 2: 让 LLM 总结文本内容
**Action**: `llm_prompt_call`
**Input**:
- file_content
**Output**:
- llm_output

```prompt
Please summarize the following context briefly in English with emoji:
Context from file: {{file_content}}
```

## Step 3: 写入结果文件
**Action**: `file_writer`
**Input**:
- llm_output
- target_file
**Output**:
- file_writer_status
- written_file_path

```content
【自动总结结果】
{{llm_output}}
```
