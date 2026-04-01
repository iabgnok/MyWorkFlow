
*Document Type: DOCX*

# MyWorkflow 设计文档

> Agent 工作流系统 — 完整设计与开发文档

*v1.0 · 2026*

## 1. 项目概述

### 1.1 关于本项目

本项目是一个面向 Agent 工作场景的自动化工作流引擎，旨在将原子 Agent Skill 封装并组合成可复用的工作流（Workflow），以实现复杂任务的自动化与可控化。

### 1.2 Workflow 与 Agent Skill 的区别

- Agent Skill：原子操作，单一职责、无状态、可直接调用。
- Workflow：高阶编排，组合多个 Skill，支持人工干预与条件分支。

### 1.3 终极目标

构建一个可由 Agent 自动生成、注册、测试并发布的母工作流（META_CREATOR），使用户通过自然语言即可创建并使用工作流。

## 2. 核心设计原则

### 2.1 标准性

定义统一的 Skill 接口与 .step.md 规范，保证互操作性。

### 2.2 可干预性

在关键步骤保留人工确认点（[CONFIRM]），支持用户调整与回退决策。

### 2.3 原子性

Skill 应保持最小职责、可重用、易测试。

### 2.4 幂等性分级

| 等级 | 名称 | 定义 | 失败处理策略 | 典型技能 |
|---|---|---|---|---|
| L0 | 强幂等 | 多次执行结果相同，无副作用 | 自动重试（最多 3 次） | file_reader, http GET |
| L1 | 条件幂等 | 需 guard 验证副作用 | guard 检查后跳过或重试 | file_writer, git_commit |
| L2 | 非幂等 | 每次执行产生副作用，需人工确认 | 禁止自动重试，触发 user_confirm | send_email, rm, delete API |

### 2.5 可追溯性

记录结构化日志（输入、输出、trace_id、时间戳），并持久化到 SQLite 以支持恢复与审计。

## 3. 技术选型

### 3.1 选型摘要

- 入口层：sentence-transformers / Pydantic
- 编排层：python-frontmatter / mistune / transitions
- 引擎层：asyncio / aiosqlite / tenacity

### 3.2 核心依赖（示例，写入 `pyproject.toml`）

```toml
[project.optional-dependencies]
dev = ["bandit", "pytest", "pytest-asyncio", "hypothesis", "pytest-mock"]
```

## 4. 系统架构与模块设计

## 4.1 目录结构

.agent/

├── entry/
│   ├── META_CREATOR.skill.md      # 母工作流入口
│   └── ...                        # 动态生成的子工作流入口
├── workflows/
│   ├── meta/                      # 母工作流专用元子工作流
│   │   ├── workflow_designer.step.md
│   │   ├── security_validator.step.md
│   │   ├── registry_manager.step.md
│   │   ├── unit_test_generator.step.md
│   │   └── report_generator.step.md
│   ├── dev/                       # 动态生成的业务工作流
│   └── index.json                 # 工作流注册表
├── engine/
│   ├── runner.py                  # 异步控制循环
│   ├── parser.py                  # Markdown + frontmatter 解析
│   ├── state_store.py             # SQLite 持久化
│   ├── error_policy.py            # 错误处理策略映射
│   └── init.py                    # 冷启动 bootstrap 脚本
├── skills/
│   └── atomic/
│       ├── file_reader.py
│       ├── file_writer.py
│       ├── shell_executor.py
│       ├── http_client.py
│       ├── git_operator.py
│       ├── user_confirm.py        # 人工介入安全闸
│       ├── log_recorder.py
│       ├── llm_prompt_call.py
│       ├── context_manager.py
│       └── registry_manager.py
├── test/                          # 自动生成的工作流校验脚本
└── logs/                          # trace.json 运行轨迹

## 4.2 模块职责说明

## 4.2.1 入口层 entry/

入口层是 Agent 的"感知器官"，实现形式为 .skill.md 文件，符合 OpenAI Tool Call / VS Code MCP 协议。核心任务是解决语义触发问题——告知 LLM 在何种场景下停止发散思考、进入预设的工作流模式。

配置项包含三个关键部分：

Triggers：关键词列表与模糊语义描述（支持 sentence-transformers 余弦相似度匹配）。
Execution Command：调用 engine/runner.py 的底层命令，如 python3 .agent/engine/runner.py --id ut_001。
Parameters：声明执行流所需变量的 Pydantic schema，LLM 负责填充，Pydantic 负责校验。

## 4.2.2 编排层 workflows/

.step.md 文件是业务逻辑的"真理源"，采用 YAML frontmatter + Markdown 正文的混合格式。frontmatter 声明元数据（id, version, inputs, outputs），正文声明每个步骤的技能调用、幂等等级和变量引用。

index.json 是所有工作流的动态索引表，格式如下：

{

"ut_001": {

"path": "workflows/dev/unit_test.step.md",

"description": "为指定 Python 文件生成 pytest 单元测试",

"version": "1.2"

}

}

## 4.2.3 引擎层 engine/

引擎层是系统的核心，除了基础的四个模块，应对高阶工程挑战还规划了两个补强模块：

- **parser.py**：用 mistune 解析 Markdown AST，提取 ## Step 标题、[Skill: xxx] 标记和 {{variable}} 占位符；用 python-frontmatter 解析 YAML 元数据。面对 “非结构化的 Markdown 文本准确映射回结构化的变量（Variable Injection）” 的开销，解析层做了大量字符串清洗和缓存优化以解决 Schema 漂移。
- **runner.py**：asyncio 异步控制循环，维护 State 对象，将上一步输出注入下一步输入。需重点处理“幽灵任务”的副作用清理（状态一致性）以及高并发争抢（文件 lock 死锁检测与超时管理）。
- **state_store.py**：基于 aiosqlite 的 SQLite 存储，每步提交一次事务，崩溃后可按 run_id 恢复到最后一个 done 状态。
- **error_policy.py**：策略映射表，将技能类型和幂等等级映射到具体的错误处理行为。
- **context_manager.py (补强：上下文窗口管理器)**：针对 LLM 上下文有限的缺陷，引入 “状态摘要（State Summary）” 机制。仅保留当前步骤的前 2 步完整输入输出；早期的状态对象通过 `llm_prompt_call` 进行压缩，仅保留关键结果变量，释放 Context Window。
- **secrets_vault.py (补强：敏感信息保险箱)**：严禁在 `.step.md` 或 `index.json` 中明文存储 API Key。通过在 `.env` 中定义加密变量，由 runner 在阶段性执行时，根据 Skill 声明的 `required_secrets` 实行变量动态注入环境。

> **延伸：冷启动/动态加载安全隔离**  
> 使用 `importlib.util` 动态加载脚本时面临“命名污染”与恶意代码内存级攻击风险。在底层引擎载入第三方或机器生成的运行时脚本前，不仅要求 Bandit 级别漏洞扫描（静态查杀），更需要在沙箱或安全上下文中进行。

## 4.2.4 原子层 skills/atomic/

所有原子技能必须实现标准接口协议：

```python
from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class SkillResult:
  success: bool
  output: Any
  error: Optional[str] = None

async def execute(params: dict) -> SkillResult:
  """必须实现，核心执行逻辑"""
  ...

async def rollback(params: dict, snapshot: dict) -> SkillResult:
  """可选，仅 L2 非幂等技能需要实现"""
  ...
```

## 5. 错误处理策略

## 5.1 策略映射表

错误处理行为由技能类型和幂等等级共同决定，在 engine/error_policy.py 中统一声明，可被 .step.md 的 frontmatter 局部覆盖：

```python
from enum import Enum
from dataclasses import dataclass

class FailureAction(Enum):
  RETRY = "retry"
  CONFIRM = "confirm"
  ROLLBACK = "rollback"
  SKIP = "skip"

@dataclass
class ErrorPolicy:
  max_retries: int = 3
  backoff_base: float = 2.0
  action_on_exhaust: FailureAction = FailureAction.CONFIRM

DEFAULT_POLICIES = {
  "file_reader": ErrorPolicy(3, 2.0, FailureAction.CONFIRM),
  "shell_executor": ErrorPolicy(2, 2.0, FailureAction.CONFIRM),
  "llm_prompt_call": ErrorPolicy(2, 3.0, FailureAction.CONFIRM),
  "http_client": ErrorPolicy(3, 2.0, FailureAction.CONFIRM),
  "DANGER": ErrorPolicy(0, 0.0, FailureAction.ROLLBACK),
}
```

## 5.2 Rollback 分级

Rollback 不是万能的，需按技能类型分级实现：
**file_writer**
备份原文件（snapshot），失败时恢复备份
**git_commit**
git reset --soft HEAD~1 撤销提交
**file_reader / http_client / llm_prompt_call**
无副作用，仅标记 step status = aborted，无需实际回滚
**shell_executor（[DANGER] 标记）**
执行前强制 user_confirm，拒绝后直接 ROLLBACK

## 6. 冷启动与 Bootstrap 机制

## 6.1 问题分析

META_CREATOR 是"用工作流创建工作流"的母工作流，存在自举问题：首次冷启动时，没有任何工作流存在，META_CREATOR 自身无法依赖运行时生成。

## 6.2 分阶段初始化流程

| 阶段 | 内容 | 触发方式 |

|---|---|---|

| 阶段 0：硬编码核心 | 5 个核心原子技能 + meta/ 下所有元子工作流 + META_CREATOR.skill.md，直接存在于 Git 仓库 | 随代码提交，永远存在 |

| 阶段 1：bootstrap | init.py 校验核心技能完整性、index.json 可写性、LLM 连通性，并将 meta/ 工作流注册进 index.json | 首次安装 / CI 流水线 / 手动执行 |

| 阶段 2：META_CREATOR 就绪 | 阶段 1 成功后，META_CREATOR 可正常运行，开始生成业务工作流 | 阶段 1 成功后自动解锁 |

| 运行时：业务工作流 | workflows/dev/ 下的子工作流由 META_CREATOR 动态生成和注册 | 用户通过自然语言请求触发 |

## 6.3 Bootstrap 脚本（engine/init.py）

REQUIRED_SKILLS = [

"file_reader", "file_writer",

"llm_prompt_call", "user_confirm",

"log_recorder", "registry_manager", "shell_executor"

]

def bootstrap():

checks = [

_check_core_skills_exist(),   # 验证 7 个核心技能文件存在

_check_index_writable(),      # 验证 index.json 可写（不存在则创建）

_check_llm_reachable(),       # 发最小 ping 请求确认 LLM 可用

_register_core_workflows(),   # 将 meta/ 工作流写入 index.json

]

if not all(checks):

raise BootstrapError("冷启动失败，请检查上述依赖条件")

print("Bootstrap OK — META_CREATOR 已就绪")

## 7. 状态管理与崩溃恢复

## 7.1 存储方案

放弃内存字典 + trace.json 文件的方案，改用 aiosqlite 事务写入。每个 Step 状态在写入后立即 commit，消除崩溃窗口期。

## 7.2 数据表结构

```sql
CREATE TABLE IF NOT EXISTS step_states (
  run_id TEXT NOT NULL, -- uuid4，每次调用 Runner 唯一
  step_index INTEGER NOT NULL, -- Step 在工作流中的顺序索引
  skill_name TEXT,
  status TEXT, -- pending/running/done/failed/skipped/aborted
  input_json TEXT, -- JSON 序列化的输入参数
  output_json TEXT, -- JSON 序列化的输出结果
  error_msg TEXT,
  ts_start REAL, -- Unix timestamp
  ts_end REAL,
  PRIMARY KEY (run_id, step_index)
);
```

## 7.3 崩溃恢复逻辑

```python
async def resume_from(self, run_id: str) -> int:
  """返回上次崩溃时，下一个需要执行的 step_index"""
  async with aiosqlite.connect(self.db_path) as db:
    cur = await db.execute(
      "SELECT MAX(step_index) FROM step_states WHERE run_id=? AND status='done'",
      (run_id,)
    )
    row = await cur.fetchone()
  return (row[0] + 1) if row[0] is not None else 0

# Runner 启动时：
# resume_idx = await state_store.resume_from(run_id)
# 从 resume_idx 开始执行，跳过之前已 done 的 Step
# 前序 Step 的输出从 DB 读回 State 对象，无需重跑
```

## 7.4 并发保护

run_id 隔离：每次调用 Runner 生成唯一 uuid4 作为 run_id，同一工作流的并发实例数据完全独立，不存在竞态。

index.json 写锁：所有对注册表的写入操作通过 `filelock` 串行化，超时 10 秒则报错。

```python
with FileLock(".agent/workflows/index.lock", timeout=10):
  data = json.loads(INDEX_PATH.read_text())
  data[workflow_id] = {"path": ..., "version": ...}
  INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
```

## 8. 母工作流（META_CREATOR）主流程设计

## 8.1 触发入口

META_CREATOR 由用户的自然语言请求触发，典型触发场景包括：

"帮我创建一个自动生成 API 文档的工作流"
"我需要一个每次 commit 前自动运行 lint 的流程"
"把我们的代码审查 SOP 做成一个工作流"

Agent 扫描 `entry/META_CREATOR.skill.md`，匹配触发语义后，调用：

```bash
python3 .agent/engine/runner.py --id meta_creator --request "用户原始需求"
```

## 8.2 主流程步骤定义（META_CREATOR.step.md）

```yaml
id: meta_creator
version: "1.0"
persona:
  role: "资深后端架构师"
  tone: "专业、严谨、带有一点批判性思维"
  constraints:
    - "禁止在未检查安全性的情况下批准 PR"
    - "必须使用 Markdown 格式输出代码片段"
inputs:
  - name: user_request
    type: str
    required: true
outputs:
  - name: workflow_id
    type: str
  - name: report
    type: str
```

> **设计补充：引入“Agent 人格”（Persona）概念**  
> 为了让生成的工作流更具场景化，在 META_CREATOR 的设计阶段引入 persona 概念。通过在 `.step.md` 的 frontmatter 增加 persona 字段，能有效限定 LLM Prompt 行为，使其工作流创建表现出更特定专业的人格与强制性约束。

## Step 1: 需求澄清与范围确认  [CONFIRM]

idempotency: L1

[Skill: llm_prompt_call]

prompt: |
  将用户需求 {{user_request}} 转化为结构化的工作流需求规格，
  包含：目标描述、输入输出、预期步骤数量、涉及的外部系统

output_schema: WorkflowSpec

Output: workflow_spec

## Step 2: 工作流设计  [SUB_WORKFLOW]

idempotency: L1

[Workflow: meta/workflow_designer]

Input: workflow_spec

Output: step_md_source, skill_gap_list

## Step 3: 安全扫描  [SUB_WORKFLOW]

idempotency: L0

[Workflow: meta/security_validator]

Input: step_md_source

Output: step_md_source_secured

## Step 4: 缺失技能确认  [CONFIRM]

idempotency: L2

condition: "len({{skill_gap_list}}) > 0"

[Skill: user_confirm]

message: "以下技能尚未实现：{{skill_gap_list}}，是否继续（将生成占位 Skill）？"

Output: confirmed

## Step 5: 注册工作流  [SUB_WORKFLOW]

idempotency: L1

[Workflow: meta/registry_manager]

Input: step_md_source_secured, workflow_spec

Output: workflow_id, entry_path

## Step 6: 生成测试  [SUB_WORKFLOW]

idempotency: L1

[Workflow: meta/unit_test_generator]

Input: step_md_source_secured, workflow_id

Output: test_results

## Step 7: 生成报告  [SUB_WORKFLOW]

idempotency: L0

[Workflow: meta/report_generator]

Input: workflow_id, test_results, workflow_spec

Output: report

## 8.3 关键决策点说明

## 9. 元子工作流详细流程设计

## 9.1 workflow_designer.step.md — 设计模组

负责将结构化需求规格转化为可执行的 .step.md 源码，并检测技能缺口。

## Step 1: 生成步骤草稿

idempotency: L1

[Skill: llm_prompt_call]

prompt: "根据 {{workflow_spec}} 生成工作流步骤清单，

每个步骤包含：描述、所需技能名称、输入变量、输出变量、幂等等级"

output_schema: StepDraft[]

Output: step_drafts

## Step 2: 技能覆盖度检查

idempotency: L0

[Skill: file_reader]

Input: ".agent/skills/atomic/" -> skill_list

## Step 3: 计算技能缺口

idempotency: L0

[Skill: llm_prompt_call]

prompt: "对比 {{step_drafts}} 中需要的技能与 {{skill_list}} 中已有的技能，

列出缺失的技能名称和建议实现方式"

Output: skill_gap_list

## Step 4: 生成 .step.md 源码

idempotency: L1

[Skill: llm_prompt_call]

prompt: "将 {{step_drafts}} 渲染为符合系统格式规范的 .step.md 源码，

包含完整 frontmatter 和每步的 idempotency 声明"

output_schema: StepMdSource

Output: step_md_source

## 9.2 security_validator.step.md — 安全扫描模组

对生成的 .step.md 进行静态安全分析，自动植入安全标识，防止危险操作未经确认直接执行。

## Step 1: 提取所有 Shell 命令和文件操作

idempotency: L0

[Skill: llm_prompt_call]

prompt: "从 {{step_md_source}} 中提取所有可能的 shell 命令、

文件删除/覆盖、网络请求、外部 API 调用"

Output: operation_list

## Step 2: bandit 静态扫描（如有内联脚本）

idempotency: L0

[Skill: shell_executor]

cmd:

```bash
bandit -r {{inline_scripts_path}} -f json
```

Output: bandit_report

## Step 3: 危险操作分级标注

idempotency: L0

[Skill: llm_prompt_call]

prompt: "根据 {{operation_list}} 和 {{bandit_report}}，

将操作分为三类：safe / needs_confirm([CONFIRM]) / dangerous([DANGER])"

Output: risk_labels

## Step 4: 植入安全标识

idempotency: L1

[Skill: llm_prompt_call]

prompt: "将 {{risk_labels}} 中 needs_confirm 和 dangerous 的步骤

对应地在 {{step_md_source}} 中插入 [CONFIRM] 或 [DANGER] 标识"

Output: step_md_source_secured

## Step 5: 死循环检测

idempotency: L0

[Skill: llm_prompt_call]

prompt: "分析 {{step_md_source_secured}} 的控制流，检测是否存在无终止条件的循环"

Output: loop_check_result

## Step 6: 安全报告输出

idempotency: L0

[Skill: log_recorder]

Input: risk_labels, loop_check_result, bandit_report

Output: security_report

## 9.3 registry_manager.step.md — 注册模组

将通过安全审查的工作流写入文件系统，生成对应的入口文件，并更新注册表。

## Step 1: 确定文件路径

idempotency: L0

[Skill: llm_prompt_call]

prompt: "根据 {{workflow_spec.name}} 生成符合 snake_case 规范的文件名"

Output: file_name

## Step 2: 写入 .step.md 文件

idempotency: L1

[Skill: file_writer]

guard: "check if workflows/dev/{{file_name}}.step.md exists"

Input: step_md_source_secured -> "workflows/dev/{{file_name}}.step.md"

Output: step_file_path

## Step 3: 生成入口 .skill.md  [CONFIRM]

idempotency: L1

[Skill: llm_prompt_call]

prompt: "根据 {{workflow_spec}} 生成对应的 entry/*.skill.md，

包含 Triggers, Execution Command, Parameters"

Output: skill_md_source

## Step 4: 写入入口文件

idempotency: L1

[Skill: file_writer]

guard: "check if entry/{{file_name}}.skill.md exists"

Input: skill_md_source -> "entry/{{file_name}}.skill.md"

Output: entry_file_path

## Step 5: 更新 index.json  [filelock]

idempotency: L1

[Skill: registry_manager]

Input: workflow_id, step_file_path, workflow_spec

Output: registered

## Step 6: 注册验证

idempotency: L0

[Skill: shell_executor]

cmd:

```bash
python3 .agent/engine/runner.py --validate-entry {{entry_file_path}}
```

Output: validation_result

## 9.4 unit_test_generator.step.md — 测试生成模组

为新生成的工作流自动创建测试脚本，验证关键步骤的输入输出契约。

## Step 1: 提取关键步骤和契约

idempotency: L0

[Skill: llm_prompt_call]

prompt: "从 {{step_md_source_secured}} 中提取：

每个步骤的输入变量类型、输出变量类型、幂等等级、

以及可能的边界条件（空输入、超时、LLM 返回格式错误等）"

Output: test_specs

## Step 2: 分析依赖的技能

idempotency: L0

[Skill: file_reader]

Input: "skills/atomic/" -> atomic_skill_list

## Step 3: 生成 pytest 测试代码

idempotency: L1

[Skill: llm_prompt_call]

prompt: "根据 {{test_specs}} 生成 pytest 测试，要求：

1. 用 pytest-mock mock 掉所有 LLM 调用和外部 IO

2. 覆盖正常路径、边界条件、错误处理三类场景

3. 异步 Step 使用 @pytest.mark.asyncio"

Output: test_code

## Step 4: 写入测试文件

idempotency: L1

[Skill: file_writer]

Input: test_code -> "test/test_{{workflow_id}}.py"

Output: test_file_path

## Step 5: 运行测试

idempotency: L0

[Skill: shell_executor]

cmd:

```bash
pytest {{test_file_path}} -v --tb=short
```

Output: test_results

## 9.5 report_generator.step.md — 报告生成模组

将整个工作流创建过程的结果汇总，生成面向用户的自然语言报告。

## Step 1: 收集执行轨迹

idempotency: L0

[Skill: context_manager]

Input: run_id -> all_step_states

## Step 2: 生成报告正文

idempotency: L0

[Skill: llm_prompt_call]

prompt: "根据以下信息生成用户友好的中文报告：

- 工作流 ID：{{workflow_id}}

- 需求规格：{{workflow_spec}}

- 测试结果：{{test_results}}（高亮失败项）

- 执行轨迹：{{all_step_states}}（摘要，不超过 5 条关键事件）

报告需包含：创建结果、触发方式示例、已知局限、后续建议"

Output: report_text

## Step 3: 记录最终日志

idempotency: L0

[Skill: log_recorder]

Input: report_text, workflow_id, run_id

Output: log_path

## 10. 各模块协作时序

## 10.1 完整调用链

以用户请求"创建单元测试工作流"为例，系统各模块的调用顺序如下：

用户在 VS Code 中输入自然语言需求，Agent 扫描 entry/ 目录，通过语义匹配命中 META_CREATOR.skill.md。
Agent 自动执行：

```bash
python3 runner.py --id meta_creator --request "用户原始需求"
```

engine/init.py 检查 bootstrap 状态，确认所有核心依赖就绪。
runner.py 启动，生成 run_id（uuid4），调用 state_store 初始化本次执行记录。
runner.py 查询 index.json，加载 META_CREATOR 的 .step.md 文件路径。
parser.py 解析 .step.md，提取 frontmatter 元数据和步骤队列，构建任务列表。
runner.py 按顺序执行任务队列：遇到 [SUB_WORKFLOW] 递归启动子工作流，遇到 [CONFIRM] 暂停等待用户确认。
每个步骤执行后，state_store 将结果事务写入 SQLite，log_recorder 写入结构化日志。
所有步骤完成后，report_generator 汇总结果，Runner 将报告交还给 Agent。
Agent 向用户播报：新工作流已创建，触发方式为……

## 10.2 职责边界总结

| 层级 | 职责范围 | 不负责 |
|---|---|---|

| entry/ | 语义触发、参数提取、启动 Runner | 执行任何业务逻辑 |

| workflows/ | 声明做什么（步骤序列） | 声明怎么做（技能内部逻辑） |

| engine/runner.py | 控制流调度、状态管理、错误路由 | 执行任何技能逻辑 |

| engine/parser.py | Markdown 解析、变量替换 | 逻辑判断、状态写入 |

| skills/atomic/ | 执行单一原子操作 | 感知工作流上下文、记录全局状态 |

| logs/ | 运行轨迹记录（只读历史） | 触发补偿逻辑、自动修复 |

## 11. 安全设计

## 11.1 三道安全防线

| 防线 | 实现机制 | 覆盖范围 |
|---|---|---|

| 静态扫描 | security_validator 在注册阶段对所有 .step.md 进行 bandit 扫描和语义分析，自动植入 [CONFIRM]/[DANGER] 标识 | 工作流生成时 |

| 运行时拦截 | runner.py 识别 [CONFIRM] 和 [DANGER] 标识，在执行前强制调用 user_confirm 暂停，等待人工授权 | 工作流每次运行时 |

| Rollback 保护 | L2 非幂等步骤失败后自动调用 rollback()，L1 步骤通过 guard 避免重复副作用 | 步骤失败时 |

## 11.2 危险关键词列表（可扩展）

```python
DANGER_KEYWORDS = [
  "rm", "rmdir", "shutil.rmtree",  # 文件删除
  "send_email", "requests.post",     # 外部通信
  "subprocess", "os.system",         # Shell 执行
  "DROP TABLE", "DELETE FROM",       # 数据库破坏性操作
  "git push", "git reset --hard",    # Git 破坏性操作
]

CONFIRM_KEYWORDS = [
  "file_writer", "git_commit",       # 有副作用的写操作
  "http POST", "http PUT", "http PATCH",
  "deploy", "publish",
]
```

## 12. 测试策略

## 12.1 测试分层

| 层级 | ## **测试目标** | 工具 | ## **Mock 策略** |
| --- | --- | --- | --- |
| 原子技能单元测试 | 验证每个 execute() 的输入输出契约 | pytest + pytest-asyncio | mock 所有外部 IO |
| 工作流集成测试 | 验证步骤间数据流转和状态机流转 | pytest + pytest-mock | mock LLM 调用，真实执行文件/Shell 操作 |
| 错误处理测试 | 覆盖重试、rollback、user_confirm 路径 | pytest | 注入受控异常 |
| 属性测试（Fuzz） | 验证 parser.py 对畸形输入的健壮性 | hypothesis | 自动生成随机 Markdown 输入 |
| Bootstrap 测试 | 验证 init.py 幂等性（反复执行不产生副作用） | pytest | 隔离文件系统 |

## 12.2 测试命名规范

test/

├── test_skills/

│   ├── test_file_reader.py

│   ├── test_shell_executor.py

│   └── ...

├── test_engine/

│   ├── test_parser.py

│   ├── test_runner.py

│   └── test_state_store.py

└── test_workflows/           # unit_test_generator 自动生成

└── test_ut_001.py

## 13. 版本管理与未来扩展

## 13.1 配置即代码

所有工作流文件随代码仓库提交，不同 Git 分支可以有不同的 SOP 集合，实现"配置即代码"。生产环境和开发环境的工作流集可以通过 Git 分支隔离，切换分支即切换流程集。

## 13.2 工作流版本控制

每个 .step.md 的 frontmatter 中包含 version 字段，index.json 存储当前激活版本。Runner 加载时按版本号查找文件，支持多版本共存和灰度切换。

## 13.3 扩展方向

并行步骤：在 .step.md 中支持 parallel: [step_a, step_b] 语法，Runner 使用 asyncio.gather 并发执行无依赖的步骤。
工作流市场：将 workflows/dev/ 发布为共享仓库，支持跨项目导入和复用。
可视化监控：基于 state_store 的 SQLite 数据，构建实时的工作流执行看板。
条件分支：在 .step.md 中支持 condition: "{{var}} == value" 语法，实现动态跳转。
人机协同优化：记录用户每次 [CONFIRM] 的决策历史，训练分类模型逐步减少不必要的确认请求。
