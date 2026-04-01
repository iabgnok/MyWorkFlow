# MyWorkflow v2.0 完整模块设计文档

> 综合设计文档 · 基于 V1.0 原始设计、模块深度设计、V2.0 架构演进与多轮审查意见整合
> 状态：V2.0 Core Architecture · 2026

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构总览](#2-系统架构总览)
3. [入口层 entry/](#3-入口层-entry)
4. [引擎层 engine/](#4-引擎层-engine)
   - 4.1 parser.py
   - 4.2 runner.py
   - 4.3 state_store.py
   - 4.4 error_policy.py
   - 4.5 context_manager.py
   - 4.6 secrets_vault.py
   - 4.7 init.py
5. [原子技能层 skills/atomic/](#5-原子技能层-skillsatomic)
6. [元工作流层 workflows/meta/](#6-元工作流层-workflowsmeta)
   - 6.1 META_CREATOR 主流程（三角色闭环）
   - 6.2 workflow_planner.step.md
   - 6.3 workflow_designer.step.md
   - 6.4 quality_evaluator.step.md
   - 6.5 registry_manager.step.md
   - 6.6 unit_test_generator.step.md
   - 6.7 report_generator.step.md
7. [核心策略汇总](#7-核心策略汇总)
8. [安全设计](#8-安全设计)
9. [状态管理与崩溃恢复](#9-状态管理与崩溃恢复)
10. [测试策略](#10-测试策略)
11. [版本管理与演进路线](#11-版本管理与演进路线)
12. [模块间接口契约](#12-模块间接口契约)

---

## 1. 项目概述

### 1.1 项目定位

MyWorkflow 是一个面向 Agent 工作场景的自动化工作流引擎。核心目标是将原子 Agent Skill 封装并组合成可复用的工作流（Workflow），实现复杂任务的自动化与可控化。

**终极目标**：构建一个可由 Agent 自动生成、注册、测试并发布的母工作流（META_CREATOR），使用户通过自然语言即可创建并使用工作流。

### 1.2 V1 → V2 核心演进

| 演进维度 | V1.0 | V2.0 | 带来的价值 |
|---|---|---|---|
| **逻辑流转** | 线性顺序执行 | 带 Evaluator 反馈的生成-评审迭代闭环 | 显著提升大型复杂流程生成产物的成功率 |
| **上下文管理** | LLM 语义摘要压缩 | 基于 SQLite 静态快照的 Context Reset（硬重置） | 彻底消除长流程中的 LLM 幻觉与注意力漂移 |
| **角色协同** | 单一全能节点 | Planner-Generator-Evaluator 三位一体 | 引入"挑剔的"对抗审查，防止自评偏乐观 |
| **任务编排** | 全部平铺 | 动态路由 + 结构性子工作流拆解 | 让引擎具备自主应对超复杂任务的拆解能力 |
| **安全与求值** | `eval` 动态求值 | simpleeval 沙盒 + 序列化脱敏 + 静态规则优先 | 工业级安全保障执行环境 |

### 1.3 核心设计原则

| 原则 | 说明 |
|---|---|
| **标准性** | 统一的 Skill 接口与 `.step.md` 规范，保证互操作性 |
| **可干预性** | 关键步骤保留 `[CONFIRM]` 人工确认点，支持调整与回退 |
| **原子性** | Skill 保持最小职责、可重用、易测试 |
| **幂等性分级** | L0/L1/L2 三级，决定失败处理策略 |
| **可追溯性** | 结构化日志 + SQLite 持久化，支持恢复与审计 |

### 1.4 幂等性分级规范

| 等级 | 名称 | 定义 | 失败处理策略 | 典型技能 |
|---|---|---|---|---|
| **L0** | 强幂等 | 多次执行结果相同，无副作用 | 自动重试（最多 3 次） | `file_reader`, `http GET`, `llm_prompt_call` |
| **L1** | 条件幂等 | 需 guard 验证副作用 | guard 检查后跳过或重试 | `file_writer`, `git_commit` |
| **L2** | 非幂等 | 每次执行产生不可逆副作用 | 禁止自动重试，触发 `user_confirm` | `send_email`, `rm`, `DELETE API` |

---

## 2. 系统架构总览

### 2.1 目录结构

```
.agent/
├── entry/
│   ├── META_CREATOR.skill.md          # 母工作流入口（硬编码，随代码存在）
│   └── *.skill.md                     # 动态生成的业务工作流入口
├── workflows/
│   ├── meta/                          # 母工作流专用元子工作流（硬编码）
│   │   ├── workflow_planner.step.md   # V2新增：Planner 角色
│   │   ├── workflow_designer.step.md  # Generator 角色
│   │   ├── quality_evaluator.step.md  # V2新增：独立 Evaluator 角色
│   │   ├── registry_manager.step.md
│   │   ├── unit_test_generator.step.md
│   │   └── report_generator.step.md
│   ├── dev/                           # 动态生成的业务工作流
│   └── index.json                     # 工作流注册表
├── engine/
│   ├── runner.py                      # 异步控制循环（状态机）
│   ├── parser.py                      # Markdown + frontmatter 解析
│   ├── state_store.py                 # SQLite 持久化
│   ├── error_policy.py                # 错误处理策略映射
│   ├── context_manager.py             # Context Reset 与 Handoff Artifact
│   ├── secrets_vault.py               # 敏感信息保险箱
│   └── init.py                        # 冷启动 bootstrap 脚本
├── skills/
│   └── atomic/
│       ├── file_reader.py
│       ├── file_writer.py
│       ├── shell_executor.py
│       ├── http_client.py
│       ├── git_operator.py
│       ├── user_confirm.py
│       ├── log_recorder.py
│       ├── llm_prompt_call.py
│       ├── context_manager.py
│       ├── variable_mapper.py         # V2新增：子流程变量显式映射
│       └── registry_manager.py
├── test/                              # 自动生成的工作流校验脚本
│   ├── test_skills/
│   ├── test_engine/
│   └── test_workflows/
└── logs/                              # trace.json 运行轨迹
    └── security_<run_id>.json
```

### 2.2 分层职责边界

| 层级 | 职责范围 | 不负责 |
|---|---|---|
| `entry/` | 语义触发、参数提取、启动 Runner | 执行任何业务逻辑 |
| `workflows/` | 声明做什么（步骤序列） | 声明怎么做（技能内部逻辑） |
| `engine/runner.py` | 控制流调度、状态管理、错误路由 | 执行任何技能逻辑 |
| `engine/parser.py` | Markdown 解析、变量替换 | 逻辑判断、状态写入 |
| `skills/atomic/` | 执行单一原子操作 | 感知工作流上下文、记录全局状态 |
| `logs/` | 运行轨迹记录（只读历史） | 触发补偿逻辑、自动修复 |

### 2.3 冷启动三阶段

| 阶段 | 内容 | 触发方式 |
|---|---|---|
| **阶段 0：硬编码核心** | 7 个核心原子技能 + `meta/` 下所有元子工作流 + `META_CREATOR.skill.md`，直接存在于 Git 仓库 | 随代码提交，永远存在 |
| **阶段 1：bootstrap** | `init.py` 校验核心技能完整性、`index.json` 可写性、LLM 连通性，并将 meta/ 工作流注册进 `index.json` | 首次安装 / CI 流水线 / 手动执行 |
| **阶段 2：META_CREATOR 就绪** | 阶段 1 成功后，META_CREATOR 可正常运行，开始生成业务工作流 | 阶段 1 成功后自动解锁 |

---

## 3. 入口层 entry/

### 3.1 设计目标

入口层是 Agent 的"感知器官"，实现为 `.skill.md` 文件，符合 OpenAI Tool Call / VS Code MCP 协议。核心任务是解决语义触发问题——告知 LLM 在何种场景下停止发散思考、进入预设的工作流模式。

### 3.2 .skill.md 文件结构

每个入口文件包含三个关键配置：

```yaml
---
id: meta_creator
triggers:
  keywords: ["创建工作流", "新建流程", "自动化"]
  semantic: "用户希望将某个重复性任务自动化或将 SOP 流程化"
  similarity_threshold: 0.82     # sentence-transformers 余弦相似度阈值
execution:
  command: "python3 .agent/engine/runner.py --id meta_creator --request {{user_request}}"
parameters:                      # Pydantic schema，LLM 负责填充，Pydantic 负责校验
  - name: user_request
    type: str
    required: true
    description: "用户的原始自然语言需求"
---
```

### 3.3 语义匹配策略

使用 `sentence-transformers` 进行余弦相似度匹配，阈值建议 0.80~0.85。当多个 skill.md 触发分数相近时，优先选择 `keywords` 精确命中的。

---

## 4. 引擎层 engine/

### 4.1 parser.py — Markdown 解析引擎

#### 设计目标

将非结构化的 `.step.md` 文本准确映射为结构化的 `StepDefinition` 对象列表，并支持变量占位符的延迟注入。

#### 核心数据结构

```python
@dataclass
class StepDefinition:
    index:        int
    title:        str
    skill_name:   str               # e.g. 'llm_prompt_call'
    idempotency:  str               # 'L0' | 'L1' | 'L2'
    raw_params:   Dict[str, Any]    # 原始参数（含 {{占位符}}）
    outputs:      List[str]         # 输出变量名列表
    output_mapping: Dict[str, str]  # V2新增：子流程输出变量重命名映射
    flags:        List[str]         # [CONFIRM][DANGER][SUB_WORKFLOW]
    condition:    Optional[str]     # 条件表达式字符串（由 simpleeval 求值）
    sub_workflow: Optional[str]     # 子工作流 id
    guard:        Optional[str]     # L1 guard 表达式

@dataclass
class WorkflowManifest:
    id:       str
    version:  str
    persona:  Dict[str, Any]
    inputs:   List[Dict]
    outputs:  List[Dict]
    steps:    List[StepDefinition]
```

#### 解析流水线

**第一阶段：frontmatter 提取**

使用 `python-frontmatter` 解析 YAML 元数据，`body` 为纯 Markdown 正文。

**第二阶段：步骤块切割**

```python
_STEP_RE   = re.compile(r'^## Step\s+\d+', re.MULTILINE)
_SKILL_RE  = re.compile(r'\[Skill:\s*(\w+)\]')
_WF_RE     = re.compile(r'\[Workflow:\s*([\w/]+)\]')
_OUTPUT_RE = re.compile(r'^Output:\s*(.+)$', re.MULTILINE)
_IDEM_RE   = re.compile(r'idempotency:\s*(L[012])')
_FLAG_RE   = re.compile(r'\[(CONFIRM|DANGER|SUB_WORKFLOW)\]')
_COND_RE   = re.compile(r'^condition:\s*"(.+)"', re.MULTILINE)
_GUARD_RE  = re.compile(r'^guard:\s*"(.+)"', re.MULTILINE)
_MAP_RE    = re.compile(r'^output_mapping:\s*(.+)$', re.MULTILINE)  # V2新增
```

**第三阶段：类型安全变量注入（运行时调用）**

> ⚠️ 关键策略：类型感知替换，防止嵌套 JSON 被字符串化破坏结构

```python
def inject_variables(raw_params: Dict, state: Dict) -> Dict:
    serialized = json.dumps(raw_params)
    def replacer(m):
        key = m.group(1).strip()
        val = state.get(key, m.group(0))
        if isinstance(val, str):
            return val          # 字符串直接替换，不额外包引号
        return json.dumps(val, ensure_ascii=False)  # 非字符串保留 JSON 表示
    injected = re.sub(r'\{\{(\w[\w.]*)\}\}', replacer, serialized)
    return json.loads(injected)
```

**缓存策略**

```python
@lru_cache(maxsize=64)
def cached_parse(path: str) -> WorkflowManifest:
    return parse_manifest(Path(path))
```

同一 path 的 manifest 在进程内只解析一次，避免重复 IO。

**Schema 漂移防护**

解析后对 `StepDefinition` 中每个 `raw_params` 键名进行 hash 指纹计算，写入 `state_store`。下次恢复时若指纹不匹配，强制触发 `[CONFIRM]` 提示用户工作流已变更。

---

### 4.2 runner.py — 异步控制循环（状态机）

#### 设计目标

作为整个执行链路的总调度器，维护 `RunState` 对象，按序驱动步骤执行，处理条件分支、子工作流递归调用、Jump Back 反馈闭环，以及所有控制流异常路由。

#### RunState 定义

```python
@dataclass
class RunState:
    run_id:         str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id:    str = ""
    variables:      Dict[str, Any] = field(default_factory=dict)
    current_step:   int = 0
    status:         str = "running"   # running | paused | done | failed
    retry_count:    int = 0           # V2新增：当前节点退回计数器
    champion:       Optional[str] = None  # V2新增：当前评分最高版本草案
```

#### 主控循环（含 V2 Jump Back 逻辑）

```
Runner.run()
    │
    ├─ 加载 manifest（cached_parse）
    ├─ 恢复断点（state_store.resume_from）
    │
    └─ for step in manifest.steps[current_step:]:
        │
        ├─ [条件求值] simpleeval 安全求值 step.condition → 跳过
        │
        ├─ [子工作流] output_mapping 显式变量映射后递归 Runner.run()
        │
        ├─ [DANGER] 强制 user_confirm → 拒绝则 aborted
        │
        ├─ [CONFIRM] user_confirm → 拒绝则 paused
        │
        ├─ [执行技能] inject_variables → skill.execute(params)
        │
        ├─ [成功] 更新 state.variables，state_store.mark(done)
        │
        └─ [失败] error_policy → RETRY | SKIP | ROLLBACK
                      │
                      └─ [Evaluator REJECTED] → Jump Back
                             ├─ 检查 token 阈值
                             │   ├─ < 60%：保留历史，追加 feedback
                             │   └─ ≥ 60%：Context Reset（清空历史，注入 Handoff Artifact）
                             ├─ retry_count++
                             └─ 根据 Escalation Ladder 决策处理方式
```

#### 子工作流变量映射（V2 关键改进）

废除 `state.variables.update(sub_outputs.variables)` 的全局污染写法，改用显式映射：

```yaml
## Step 3: 调用安全校验子工作流
[SUB_WORKFLOW: security_validator]
output_mapping:
  security_report: sec_report_v2     # 重命名避免冲突
  step_md_source_secured: secured_source
```

Runner 执行时按 `output_mapping` 注入，未声明的子工作流输出变量不进入父命名空间。

#### 幽灵任务清理

```python
async def cleanup_ghost_runs(store: StateStore, timeout_seconds: int = 3600):
    """进程意外中断时，标记超时的 running 步骤为 aborted"""
    await store.abort_stale_runs(timeout_seconds)
```

#### 文件锁死锁保护

```python
# 注册 SIGTERM/SIGINT handler，确保 FileLock 被释放
signal.signal(signal.SIGTERM, _cleanup_on_exit)
signal.signal(signal.SIGINT, _cleanup_on_exit)
```

---

### 4.3 state_store.py — SQLite 持久化层

#### 数据表结构

```sql
CREATE TABLE IF NOT EXISTS step_states (
    run_id       TEXT NOT NULL,
    step_index   INTEGER NOT NULL,
    skill_name   TEXT,
    status       TEXT,    -- pending/running/done/failed/skipped/aborted
    input_json   TEXT,    -- 脱敏后的 JSON（required_secrets 替换为 "***"）
    output_json  TEXT,    -- 脱敏后的 JSON
    error_msg    TEXT,
    ts_start     REAL,
    ts_end       REAL,
    PRIMARY KEY (run_id, step_index)
);

CREATE TABLE IF NOT EXISTS run_meta (
    run_id        TEXT PRIMARY KEY,
    workflow_id   TEXT,
    var_snapshot  TEXT,   -- 最新变量快照（JSON，脱敏后）
    retry_count   INTEGER DEFAULT 0,  -- V2新增：当前节点退回计数器
    champion_json TEXT,   -- V2新增：当前评分最高草案（供 Handoff 使用）
    ts_created    REAL,
    ts_updated    REAL
);
```

#### 关键策略

**每步提交原则**：每执行完一个 Step 立即 `db.commit()`，消除崩溃窗口期。

**脱敏落盘（关键安全策略）**：序列化 `input_json` 和 `output_json` 前，将 `required_secrets` 中声明的字段替换为 `"***"`，严禁 API Key 等敏感信息明文落盘。

```python
def scrub_secrets(params: dict, secret_keys: list) -> dict:
    scrubbed = params.copy()
    for key in secret_keys:
        if key in scrubbed:
            scrubbed[key] = "***"
    return scrubbed
```

**崩溃恢复逻辑**：

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
```

**并发保护**：`run_id` 隔离保证同一工作流并发实例数据完全独立；`index.json` 写操作通过 `filelock` 串行化，超时 10 秒则报错。

---

### 4.4 error_policy.py — 错误处理策略映射

#### 策略枚举

```python
class FailureAction(Enum):
    RETRY    = "retry"
    CONFIRM  = "confirm"
    ROLLBACK = "rollback"
    SKIP     = "skip"
```

#### 默认策略映射表

```python
DEFAULT_POLICIES = {
    "file_reader":     ErrorPolicy(max_retries=3, backoff_base=2.0, action_on_exhaust=FailureAction.CONFIRM),
    "shell_executor":  ErrorPolicy(max_retries=2, backoff_base=2.0, action_on_exhaust=FailureAction.CONFIRM),
    "llm_prompt_call": ErrorPolicy(max_retries=2, backoff_base=3.0, action_on_exhaust=FailureAction.CONFIRM),
    "http_client":     ErrorPolicy(max_retries=3, backoff_base=2.0, action_on_exhaust=FailureAction.CONFIRM),
    "DANGER":          ErrorPolicy(max_retries=0, backoff_base=0.0, action_on_exhaust=FailureAction.ROLLBACK),
}
```

策略可被 `.step.md` 的 frontmatter 局部覆盖。重试使用 `tenacity` 库实现指数退避。

#### Rollback 分级

| 技能 | Rollback 策略 |
|---|---|
| `file_writer` | 执行前备份原文件（`.bak`），失败时恢复 |
| `git_commit` | `git reset --soft HEAD~1` 撤销提交 |
| `file_reader` / `http_client` / `llm_prompt_call` | 无副作用，仅标记 `status = aborted` |
| `shell_executor`（`[DANGER]`） | 执行前强制 `user_confirm`，拒绝后直接 ROLLBACK |

---

### 4.5 context_manager.py — Context Reset 机制（V2 重写）

#### 设计目标

彻底废弃 LLM 语义摘要压缩方案（Compaction），改用基于 SQLite 静态快照的硬重置（Context Reset），消除长任务中的"上下文焦虑"和幻觉漂移。

#### Compaction vs Context Reset 对比

| 维度 | Compaction（旧） | Context Reset（新） |
|---|---|---|
| 机制 | 原地摘要历史，同一 Agent 继续 | 清空历史，用快照重启新 Agent |
| 上下文焦虑 | 依然存在 | 彻底消除 |
| 连续性 | 高 | 依赖 Handoff Artifact 质量 |
| 适用场景 | 短任务压缩 | 长任务、Jump Back 后重试 |

#### 触发时机（关键策略：token 阈值触发，而非每次打回都 Reset）

```python
def should_reset(current_token_count: int, context_window: int) -> bool:
    """只有 token 占用超过 60% 才触发硬重置"""
    return current_token_count / context_window >= 0.60
```

- **token < 60%**：Jump Back 时保留历史，直接追加 feedback，不 Reset
- **token ≥ 60%**：触发 Context Reset，清空 Message History，注入 Handoff Artifact 作为 System Prompt

#### Handoff Artifact 生成

```python
def build_handoff_artifact(run_id: str, from_step: int) -> dict:
    """
    从 state_store 导出当前状态，生成结构化交接快照。
    包含：当前最佳草案（Champion）、变量快照、失败反馈、下一步目标。
    """
    return {
        "run_id": run_id,
        "current_step": from_step,
        "champion_draft": state_store.get_champion(run_id),   # 当前评分最高版本
        "var_snapshot": state_store.load_variables(run_id),   # 完整变量状态
        "last_failure_feedback": state_store.get_last_feedback(run_id),  # 上一次失败原因
        "next_objective": "根据 defects 进行精准局部修正，勿全量重写"
    }
```

Champion 草案在任何情况下（包括 Reset 后）都必须通过 Handoff Artifact 完整传递给下一轮 Generator。

---

### 4.6 secrets_vault.py — 敏感信息保险箱

#### 设计目标

严禁在 `.step.md`、`index.json` 或 SQLite 中明文存储 API Key 等敏感信息。

#### 实现策略

- **V0.2（最小版本）**：从 `.env` 读取，序列化前脱敏，Key 不落盘。
- **V1.0（终态）**：内存层混淆加扰，真正的加密保险箱，`required_secrets` 声明的变量由 Runner 在执行前动态注入环境，执行完毕后立即从内存清除。

```python
# Skill 声明所需密钥
required_secrets = ["OPENAI_API_KEY", "GITHUB_TOKEN"]

# Runner 在调用技能前注入，调用后清除
async def execute_with_secrets(skill, params, vault):
    injected = vault.inject(params, skill.required_secrets)
    result = await skill.execute(injected)
    vault.revoke(injected, skill.required_secrets)
    return result
```

---

### 4.7 init.py — 冷启动 Bootstrap

```python
REQUIRED_SKILLS = [
    "file_reader", "file_writer", "llm_prompt_call",
    "user_confirm", "log_recorder", "registry_manager",
    "shell_executor", "variable_mapper"   # V2新增
]

def bootstrap():
    checks = [
        _check_core_skills_exist(),    # 验证核心技能文件存在
        _check_index_writable(),       # 验证 index.json 可写（不存在则创建）
        _check_llm_reachable(),        # 发最小 ping 请求确认 LLM 可用
        _register_core_workflows(),    # 将 meta/ 工作流写入 index.json
    ]
    if not all(checks):
        raise BootstrapError("冷启动失败，请检查上述依赖条件")
    print("Bootstrap OK — META_CREATOR 已就绪")
```

---

## 5. 原子技能层 skills/atomic/

### 5.1 标准接口协议

所有原子技能必须实现以下标准接口：

```python
from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class SkillResult:
    success: bool
    output:  Any
    error:   Optional[str] = None

async def execute(params: dict) -> SkillResult:
    """必须实现，核心执行逻辑"""
    ...

async def rollback(params: dict, snapshot: dict) -> SkillResult:
    """可选，仅 L2 非幂等技能需要实现"""
    ...
```

### 5.2 各技能设计说明

| 技能 | 幂等级 | 核心功能 | Rollback |
|---|---|---|---|
| `file_reader.py` | L0 | 读取文件内容，支持 glob 模式 | 无需 |
| `file_writer.py` | L1 | 原子写入（先写 `.tmp`，校验 MD5 后重命名） | 恢复 `.bak` 备份 |
| `shell_executor.py` | L2 | 执行 shell 命令，强制携带 `[DANGER]` | ROLLBACK |
| `http_client.py` | L0/L2 | GET 为 L0，POST/PUT/PATCH 为 L2 | 无（外部副作用） |
| `git_operator.py` | L1 | git add/commit/push | `git reset --soft HEAD~1` |
| `user_confirm.py` | L0 | 阻塞等待用户 Y/N（CLI stdin / VS Code IPC） | 无需 |
| `log_recorder.py` | L0 | 结构化写入 `logs/` 目录 | 无需 |
| `llm_prompt_call.py` | L0 | 调用 LLM API，支持字符串和 JSON 输出 | 无需 |
| `variable_mapper.py` | L0 | **V2新增**：子流程输出变量显式重命名映射 | 无需 |
| `registry_manager.py` | L1 | 读写 `index.json`，带 filelock 并发保护 | 版本回滚 |

### 5.3 file_writer.py 原子写入细节

```
1. 写入临时文件 <target>.step.md.tmp
2. 计算 MD5 校验和，验证文件完整性
3. 原子重命名为正式路径
4. 若中途崩溃，残留 .tmp 文件在下次启动时清理
```

---

## 6. 元工作流层 workflows/meta/

### 6.1 META_CREATOR 三角色闭环主流程

META_CREATOR 是系统的母工作流，V2.0 核心改造是将线性瀑布流升级为**带反馈闭环的 Planner-Generator-Evaluator 三角色迭代状态机**。

#### 总体数据流

```
用户自然语言请求
        │
        ▼
[Step 1] Planner：user_request → workflow_blueprint（含复杂性断言）
        │
        ├─ 复杂度 ≤ 7步 → 直接进入 Generator
        └─ 复杂度 > 7步 → 子流程拆分（优先完成子流程闭环）
                │
                ▼
[Step 2] Generator：workflow_blueprint → workflow_draft（全量交付）
        │
        ▼
[Step 3] Evaluator：workflow_draft → evaluation_report（四维评分 + 点对点 defect）
        │
        ├─ APPROVED（分数达标）→ [Step 4] 物理落地与注册
        └─ REJECTED → Jump Back 到 Step 2（Generator 精准 Editing）
                │
                └─ 阶梯式降级策略（Escalation Ladder）
```

#### META_CREATOR Persona 配置

```yaml
id: meta_creator
version: "2.0"
persona:
  role: "资深后端架构师"
  tone: "专业、严谨、带有一点批判性思维"
  constraints:
    - "禁止在未检查安全性的情况下批准生成的工作流"
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

---

### 6.2 workflow_planner.step.md — 规划者

**Persona**：资深系统分析师，负责需求解构，不参与实现。

#### Step 1：需求理解与意图澄清 `[L0]`

```
[Skill: llm_prompt_call]
prompt: |
  你是一位资深系统分析师。
  用户需求：{{user_request}}
  
  请输出结构化 Workflow_Blueprint：
  - name: 工作流名称（snake_case）
  - description: 功能描述
  - estimated_steps: 预估步骤数
  - inputs: 所需输入变量列表
  - outputs: 期望输出变量列表
  - step_clusters: 逻辑步骤分组（用于复杂性断言）

output_schema: WorkflowBlueprint
Output: workflow_blueprint
```

#### Step 2：复杂性断言与子流程拆分决策 `[L0]`

**子流程拆分标准（V2 关键策略）**：不使用硬阈值（废弃"7步强制拆分"），改为**基于依赖关系的结构性判断**：

> 如果某组步骤的所有输入来自外部、所有输出只被外部消费，即形成完整子闭环，则拆为子工作流。

```
[Skill: llm_prompt_call]
prompt: |
  分析以下蓝图的步骤依赖关系：
  {{workflow_blueprint}}
  
  判断标准：某组步骤若形成完整输入/输出子闭环（对外黑盒），则拆为子工作流。
  
  输出：
  - should_split: bool
  - sub_workflows: [{name, inputs, outputs, steps}]
  - main_flow_steps: [步骤描述]
  - handoff_contracts: 子流程间的交接箱契约

Output: planner_decision
```

若 `should_split == true`，母工作流**优先进入子流程生成-评审闭环**，子流程全部通过后再生成主流程组装。

---

### 6.3 workflow_designer.step.md — 生成者

**Persona**：精通 Python/Markdown 的架构级开发工程师。

#### 核心策略：全量交付 vs 精准 Editing

| 模式 | 触发条件 | 行为 |
|---|---|---|
| **全量交付** | 首次生成 | 一气呵成生成完整 `.step.md` 文件，保证全局变量连贯 |
| **精准 Editing** | 收到 Evaluator 的 REJECTED 反馈 | 读取 Champion 草案，仅对 `defects[].location` 指定的位置进行点对点修正，不全量重写 |

#### Step 1：全量生成草案 `[L1]`

```
[Skill: llm_prompt_call]
prompt: |
  你是一名精通 Python/Markdown 的架构级开发工程师。
  
  根据以下蓝图，生成完整的 .step.md 工作流源码（全量交付，一次性输出完整文件）：
  {{planner_decision}}
  
  格式规范：
  - frontmatter 包含 id, version, inputs, outputs, persona
  - 每个步骤以 "## Step N: 标题" 开头
  - 声明 idempotency 等级（L0/L1/L2）
  - 用 [Skill: xxx] 声明技能
  - 用 {{变量名}} 引用上下文变量
  - 输出变量用 "Output: 变量名" 声明
  - 子流程使用 output_mapping 显式声明变量映射
  - 危险操作标记 [DANGER]，需确认操作标记 [CONFIRM]

output_schema: StepMdSource
Output: workflow_draft
```

#### Step 2（条件触发）：精准局部修正 `[L1]`

```
[Skill: llm_prompt_call]
condition: "{{evaluation_report.status}} == 'REJECTED'"
prompt: |
  当前最佳草案（Champion）：
  {{champion_draft}}
  
  Evaluator 发现的缺陷（点对点坐标）：
  {{evaluation_report.defects}}
  
  请针对每个 defect 的 location 进行精准局部修正。
  要求：
  1. 只修改 defect 指定的位置，不改动其他内容
  2. 修正后返回完整的 .step.md 文件
  3. 在文件顶部注释说明本次修改了哪些位置及原因

Output: workflow_draft
```

---

### 6.4 quality_evaluator.step.md — 评审者（V2 新增）

**Persona**：极度挑剔、严格把控风险的首席安全架构师。默认不信任 LLM 生成的任何输出。

#### 四维评分量表

| 维度 | 权重 | 门禁类型 | 说明 |
|---|---|---|---|
| **逻辑完备性（Logic Closure）** | 40% | 一票否决（必须 100 分） | 所有 `{{var}}` 必须有确定源头；子流程输入输出契约对齐 |
| **安全与副作用控制（Safety Gate）** | 30% | 一票否决（必须 100 分） | 静态规则命中优先，不允许 LLM 降级风险；危险操作必须携带 flag |
| **工程健壮性（Engineering Quality）** | 20% | 软门禁（阈值 70 分，第三轮可忽略） | 步骤粒度合理，无过度耦合 |
| **角色约束度（Persona Adherence）** | 10% | 软门禁（阈值 60 分，第三轮可忽略） | 注释、命名符合指定规范 |

#### Step 1：静态安全扫描（规则优先）`[L0]`

```
[Skill: llm_prompt_call]
prompt: |
  对以下 .step.md 进行静态关键词扫描：
  {{workflow_draft}}
  
  危险关键词（自动标 [DANGER]，不允许降级）：
  rm, rmdir, shutil.rmtree, DROP TABLE, DELETE FROM,
  git push, git reset --hard, subprocess, os.system, shutdown
  
  需确认关键词（自动标 [CONFIRM]）：
  file_writer, git_commit, http POST/PUT/PATCH, deploy, publish, send_email
  
  静态规则匹配结果只能升级风险等级，不能降级。

Output: static_scan_result
```

#### Step 2：四维结构化评分 `[L0]`

```
[Skill: llm_prompt_call]
prompt: |
  你是首席安全架构师，对以下工作流草案进行整体评审：
  {{workflow_draft}}
  静态扫描结果：{{static_scan_result}}
  
  按四维量表打分，输出严格 JSON 格式：
  {
    "status": "APPROVED" | "REJECTED",
    "score": 0-100,
    "dimension_scores": {
      "logic_closure": int,     // 40% 权重，<100 则 REJECTED
      "safety_gate": int,       // 30% 权重，<100 则 REJECTED
      "engineering_quality": int, // 20% 权重，<70 则扣分
      "persona_adherence": int  // 10% 权重，<60 则扣分
    },
    "defects": [
      {
        "type": "LOGIC_ERROR" | "SAFETY_VIOLATION" | "QUALITY_ISSUE" | "STYLE_ISSUE",
        "location": "Step N",
        "reason": "具体原因",
        "suggestion": "修复建议"
      }
    ],
    "overall_feedback": "总体评价"
  }

Output: evaluation_report
```

#### Step 3：更新 Champion `[L1]`

```
[Skill: registry_manager]
# 若当前 score > champion_score，更新 run_meta.champion_json
condition: "{{evaluation_report.score}} > {{champion_score}}"
Input: workflow_draft, evaluation_report.score
Output: champion_updated
```

---

### 6.5 registry_manager.step.md — 注册模组

#### Step 1：确定文件路径 `[L0]`

LLM 根据 `workflow_spec.name` 生成符合 snake_case 规范的文件名。

#### Step 2：原子写入 `.step.md` 文件 `[L1]`

```
[Skill: file_writer]
guard: "skip_if_exists"
Input: step_md_source_secured -> "workflows/dev/{{file_name}}.step.md"
atomic_write: true    # 先写 .tmp，MD5 校验后原子重命名
Output: step_file_path
```

#### Step 3：生成入口 `.skill.md` `[CONFIRM][L1]`

LLM 根据 `workflow_spec` 生成对应的 `entry/*.skill.md`，包含 Triggers、Execution Command、Parameters。

#### Step 4：写入入口文件 `[L1]`

同原子写入策略，guard 防止重复写入。

#### Step 5：更新 index.json `[L1]`

```python
with FileLock(".agent/workflows/index.lock", timeout=10):
    data = json.loads(INDEX_PATH.read_text())
    # 版本号单调递增校验：拒绝旧版本覆盖新版本
    if existing := data.get(workflow_id):
        if version_tuple(new_version) <= version_tuple(existing["version"]):
            raise VersionConflictError(...)
    data[workflow_id] = {"path": ..., "version": ..., "description": ...}
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
```

#### Step 6：注册验证 `[L0]`

```bash
python3 .agent/engine/runner.py --validate-entry {{entry_file_path}}
```

---

### 6.6 unit_test_generator.step.md — 测试生成模组

#### 测试质量门禁（多维评估，不止覆盖率）

| 评估维度 | 评估方式 | 说明 |
|---|---|---|
| **完整性** | 静态分析（parser 可做） | 每个 Step 的 Output 变量都被后续步骤消费或导出 |
| **错误路径覆盖** | 静态规则 | 关键 L1/L2 步骤都有对应 rollback 或 CONFIRM |
| **幂等性合理性** | 规则校验 | LLM 生成的幂等级别与 skill 类型匹配 |
| **可终止性** | 死循环检测 | 无永远不满足的条件分支，无循环依赖 |
| **代码覆盖率** | pytest-cov | 软门禁：< 70% 告警但不阻断注册 |

#### Step 3：生成 pytest 测试代码 `[L1]`

要求：
1. 用 `pytest-mock` mock 掉所有 LLM 调用和外部 IO
2. 覆盖**正常路径、边界条件、错误处理**三类场景
3. 异步 Step 使用 `@pytest.mark.asyncio`
4. **断言必须有实质内容**（防止 `assert True` 游戏覆盖率）

---

### 6.7 report_generator.step.md — 报告生成模组

汇总整个工作流创建过程的结果，生成面向用户的自然语言报告，包含：创建结果、触发方式示例、已知局限、后续建议、历史迭代轨迹（对人工干预时有诊断价值）。

---

## 7. 核心策略汇总

### 7.1 阶梯式降级策略（Escalation Ladder）

防止 Generator 与 Evaluator 在高难度任务上陷入死循环：

| 轮次 | 机制 | 处理动作 |
|---|---|---|
| **Round 1** | 标准重试 | 完整 JSON 反馈，直接发回 Generator |
| **Round 2** | CoT 强化 | 追加强制词："You failed previously. Think step by step to solve the Defect list." |
| **Round 3** | 标准下调（Relaxation） | Evaluator 关闭 `engineering_quality` 和 `persona_adherence` 卡控，保底只要逻辑闭合且无安全缺陷即放行 |
| **Round 4** | 强制挂起（Human-in-the-loop） | 触发底层 `[CONFIRM]`，输出"已连续 3 次失败"，将 Champion 版本呈递给用户求取干预 |

### 7.2 条件求值安全策略

严禁使用 Python 内置 `eval()`，所有 `step.condition` 表达式通过 `simpleeval` 进行 AST 拦截求值：

```python
from simpleeval import simple_eval

def safe_eval_condition(expr: str, variables: dict) -> bool:
    """
    仅支持：==, !=, >, <, >=, <=, and, or, not 及变量名访问
    拒绝任何函数调用，防止 LLM 生成的条件表达式执行任意代码
    """
    return simple_eval(expr, names=variables)
```

### 7.3 安全风险等级只升不降原则

静态规则扫描结果是最高优先级，LLM 的语义分析结果只能**升级**风险等级，绝不允许降级：

```python
def merge_risk_level(static_level: str, llm_level: str) -> str:
    """静态规则 > LLM 判断，风险只能升级"""
    RISK_ORDER = {"safe": 0, "needs_confirm": 1, "dangerous": 2}
    return max([static_level, llm_level], key=lambda x: RISK_ORDER[x])
```

### 7.4 变量命名空间管理

子工作流通过 `output_mapping` 显式声明变量映射，未声明的输出变量不进入父命名空间，彻底解决递归时的全局命名污染问题。

### 7.5 版本管理策略

- **Champion 保留**：始终保留当前评分最高的草案，供 Jump Back 后的 Generator 作为修改基底。
- **失败上下文保留**：执行下一次生成时，必须带上上一次失败的原因（Last Failure Context）。
- **历史存档**：在 `.agent/logs/` 保留所有迭代记录，供人工干预时诊断。

---

## 8. 安全设计

### 8.1 三道安全防线

| 防线 | 实现机制 | 覆盖范围 |
|---|---|---|
| **静态扫描** | `quality_evaluator` 在注册阶段对所有 `.step.md` 进行关键词扫描和语义分析，自动植入 `[CONFIRM]`/`[DANGER]` 标识 | 工作流生成时 |
| **运行时拦截** | `runner.py` 识别 `[CONFIRM]` 和 `[DANGER]` 标识，在执行前强制调用 `user_confirm` 暂停，等待人工授权 | 工作流每次运行时 |
| **Rollback 保护** | L2 非幂等步骤失败后自动调用 `rollback()`，L1 步骤通过 `guard` 避免重复副作用 | 步骤失败时 |

### 8.2 危险关键词列表（可扩展）

```python
DANGER_KEYWORDS = [
    "rm", "rmdir", "shutil.rmtree",       # 文件删除
    "send_email", "requests.post",          # 外部通信（部分场景）
    "subprocess", "os.system",              # Shell 执行
    "DROP TABLE", "DELETE FROM",            # 数据库破坏性操作
    "git push", "git reset --hard",         # Git 破坏性操作
    "shutdown", "reboot",                   # 系统操作
]

CONFIRM_KEYWORDS = [
    "file_writer", "git_commit",
    "http POST", "http PUT", "http PATCH",
    "deploy", "publish",
]
```

### 8.3 动态加载安全隔离

使用 `importlib.util` 动态加载机器生成的运行时脚本时，不仅要求 Bandit 级别漏洞扫描（静态查杀），还需要在沙箱或安全上下文中进行，防止命名污染与恶意代码内存级攻击。

---

## 9. 状态管理与崩溃恢复

### 9.1 完整执行时序

```
用户输入自然语言需求
        │
        ▼
entry/ 语义匹配 → META_CREATOR.skill.md 命中
        │
        ▼
engine/init.py 检查 bootstrap 状态
        │
        ▼
runner.py 启动，生成 run_id（uuid4）
        │
        ▼
state_store 初始化本次执行记录
        │
        ▼
index.json 查询 → parser.py 解析 .step.md
        │
        ▼
runner.py 按序执行步骤队列
    ├─ [SUB_WORKFLOW] → 递归启动子工作流（output_mapping 映射）
    ├─ [CONFIRM] → 暂停等待用户确认
    ├─ [DANGER] → 强制确认
    └─ 每步完成后 → state_store 事务提交 + log_recorder 写入日志
        │
        ▼
report_generator 汇总结果 → Runner 返回报告给 Agent
        │
        ▼
Agent 向用户播报：新工作流已创建，触发方式为……
```

### 9.2 崩溃恢复逻辑

Runner 启动时检查 `run_id` 是否有历史记录，若有则从最后一个 `done` 状态的步骤之后继续，前序步骤的输出变量从 DB 恢复，无需重跑。

---

## 10. 测试策略

### 10.1 测试分层

| 层级 | 测试目标 | 工具 | Mock 策略 |
|---|---|---|---|
| 原子技能单元测试 | 验证每个 `execute()` 的输入输出契约 | pytest + pytest-asyncio | mock 所有外部 IO |
| 工作流集成测试 | 验证步骤间数据流转和状态机流转 | pytest + pytest-mock | mock LLM 调用，真实执行文件/Shell 操作 |
| 错误处理测试 | 覆盖重试、rollback、user_confirm 路径 | pytest | 注入受控异常 |
| 属性测试（Fuzz） | 验证 `parser.py` 对畸形输入的健壮性 | hypothesis | 自动生成随机 Markdown 输入 |
| Bootstrap 测试 | 验证 `init.py` 幂等性（反复执行不产生副作用） | pytest | 隔离文件系统 |

### 10.2 测试目录结构

```
test/
├── test_skills/
│   ├── test_file_reader.py
│   ├── test_file_writer.py
│   ├── test_shell_executor.py
│   ├── test_variable_mapper.py
│   └── ...
├── test_engine/
│   ├── test_parser.py
│   ├── test_runner.py
│   ├── test_state_store.py
│   └── test_context_manager.py
└── test_workflows/          # unit_test_generator 自动生成
    └── test_<workflow_id>.py
```

---

## 11. 版本管理与演进路线

### 11.1 配置即代码

所有工作流文件随代码仓库提交，不同 Git 分支可以有不同的 SOP 集合，实现"配置即代码"。

### 11.2 分阶段实现路线图

| 阶段 | 版本 | 核心目标 | 里程碑验收标准 |
|---|---|---|---|
| **阶段一** | V0.1 | 核心骨架 + MVP 验证 | `hello_world.step.md` 从头跑到尾，输出预期文件 |
| **阶段二** | V0.2 | 状态持久化 + 错误恢复 + 脱敏落盘 | Ctrl+C 后按 run_id 恢复，变量不丢失 |
| **阶段三** | V0.5 | 三角色闭环 + 子工作流嵌套 + output_mapping | 日志中观察到完整的"设计-打回-修复-注册"迭代链路，在 ≤ 4 轮内通过逻辑完备性检查 |
| **阶段四** | V1.0+ | Context Reset + Escalation Ladder + 安全沙盒 + 工业级完整性 | 一句需求触发全自动：设计→生成→测试→扫描→注册→报告 |

### 11.3 扩展方向

- **并行步骤**：`.step.md` 支持 `parallel: [step_a, step_b]` 语法，Runner 使用 `asyncio.gather` 并发执行无依赖步骤
- **工作流市场**：将 `workflows/dev/` 发布为共享仓库，支持跨项目导入复用
- **可视化监控**：基于 `state_store` 的 SQLite 数据，构建实时工作流执行看板
- **人机协同优化**：记录用户每次 `[CONFIRM]` 的决策历史，训练分类模型逐步减少不必要的确认请求
- **VS Code 深度集成**：`user_confirm` 接入 VS Code Extension IPC，实现 IDE 内弹窗审批

---

## 12. 模块间接口契约

| 调用方 | 被调用方 | 传入 | 返回 |
|---|---|---|---|
| Runner | Parser | `.step.md` 路径 | `WorkflowManifest` |
| Runner | StateStore | `run_id`, `step_index`, `status` | 无（副作用） |
| Runner | SkillModule | `params: dict` | `SkillResult` |
| Runner | Runner（递归） | `workflow_id`, `inputs` | `RunState` |
| Runner | ContextManager | `run_id`, `current_index`, `token_count` | `handoff_artifact: dict` 或 `None` |
| Runner | SecretsVault | `skill_module`, `params` | `params`（注入密钥后） |
| SkillModule | ErrorPolicy | `step: StepDefinition` | `ErrorPolicy` |
| RegistryManager | FileLock | `index.lock` 路径 | 持有锁期间独占写入 |
| Evaluator | Runner | `evaluation_report.status` | Jump Back 或 APPROVED 流转 |

---

*文档版本：V2.0 · 综合整理自设计文档、模块深度设计、V2.0 架构演进与多轮审查意见*
*最后更新：2026*
