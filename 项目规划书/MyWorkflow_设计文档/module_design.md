MyWorkflow 核心模块深度设计文档

补充完善版 · Engine · Skills · Meta Workflows · v2.0 · 2026

Part 1 · Engine 引擎层完整设计
引擎层是整个系统的神经中枢，负责将静态的 .step.md 声明转化为动态的异步执行流。以下对各子模块的内部实现逐一展开。

1.1 parser.py — Markdown 解析引擎
设计目标：将非结构化的 .step.md 文本准确映射为结构化的 StepDefinition 对象列表，并支持变量占位符的延迟注入。
核心数据结构
pythonfrom dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class StepDefinition:
    index:        int
    title:        str
    skill_name:   str               # e.g. 'llm_prompt_call'
    idempotency:  str               # 'L0' | 'L1' | 'L2'
    raw_params:   Dict[str, Any]    # 原始参数（含 {{占位符}}）
    outputs:      List[str]         # 输出变量名列表
    flags:        List[str] = field(default_factory=list)  # [CONFIRM][DANGER][SUB_WORKFLOW]
    condition:    Optional[str] = None   # 条件表达式字符串
    sub_workflow: Optional[str] = None  # 子工作流 id
    guard:        Optional[str] = None  # L1 guard 表达式

@dataclass
class WorkflowManifest:
    id:       str
    version:  str
    persona:  Dict[str, Any]
    inputs:   List[Dict]
    outputs:  List[Dict]
    steps:    List[StepDefinition]
解析流水线
pythonimport re, python_frontmatter, mistune
from functools import lru_cache
from pathlib import Path

# ── 第一阶段：frontmatter 提取 ──────────────────────────

def parse_manifest(path: Path) -> WorkflowManifest:
    post = python_frontmatter.load(str(path))
    meta = post.metadata          # YAML 元数据
    body = post.content           # Markdown 正文
    steps = _parse_steps(body)
    return WorkflowManifest(
        id=meta['id'], version=meta['version'],
        persona=meta.get('persona', {}),
        inputs=meta.get('inputs', []),
        outputs=meta.get('outputs', []),
        steps=steps,
    )

# ── 第二阶段：步骤块切割 ────────────────────────────────

_STEP_RE   = re.compile(r'^## Step\s+\d+', re.MULTILINE)
_SKILL_RE  = re.compile(r'\[Skill:\s*(\w+)\]')
_WF_RE     = re.compile(r'\[Workflow:\s*([\w/]+)\]')
_OUTPUT_RE = re.compile(r'^Output:\s*(.+)$', re.MULTILINE)
_IDEM_RE   = re.compile(r'idempotency:\s*(L[012])')
_FLAG_RE   = re.compile(r'\[(CONFIRM|DANGER|SUB_WORKFLOW)\]')
_COND_RE   = re.compile(r'^condition:\s*"(.+)"', re.MULTILINE)
_GUARD_RE  = re.compile(r'^guard:\s*"(.+)"', re.MULTILINE)

def _parse_steps(body: str) -> List[StepDefinition]:
    blocks = _STEP_RE.split(body)
    steps = []
    for i, block in enumerate(blocks[1:], start=0):
        skill_m  =_SKILL_RE.search(block)
        wf_m     = _WF_RE.search(block)
        idem_m   =_IDEM_RE.search(block)
        outputs  = [o.strip() for o in (_OUTPUT_RE.findall(block) or [""])[0].split(",")]
        flags    =_FLAG_RE.findall(block)
        cond_m   = _COND_RE.search(block)
        guard_m  =_GUARD_RE.search(block)
        title    = block.strip().split['\n'](0).strip(": ")

        steps.append(StepDefinition(
            index        = i,
            title        = title,
            skill_name   = skill_m.group(1) if skill_m else "__sub_workflow__",
            idempotency  = idem_m.group(1) if idem_m else "L0",
            raw_params   = _extract_params(block),
            outputs      = [o for o in outputs if o],
            flags        = flags,
            sub_workflow = wf_m.group(1) if wf_m else None,
            condition    = cond_m.group(1) if cond_m else None,
            guard        = guard_m.group(1) if guard_m else None,
        ))
    return steps

# ── 第三阶段：变量注入（运行时调用）────────────────────

def inject_variables(raw_params: Dict, state: Dict) -> Dict:
    """将 {{var}} 占位符替换为 state 中的实际值，深度递归处理嵌套结构"""
    import json
    serialized = json.dumps(raw_params)
    def replacer(m):
        key = m.group(1).strip()
        val = state.get(key, m.group(0))  # 未命中保留原占位符，留给下游检测
        return json.dumps[val](1:-1)      # 去除 JSON 字符串两端引号
    injected = re.sub(r'\{\{(\w+)\}\}', replacer, serialized)
    return json.loads(injected)

# ── 缓存：同一 path 的 manifest 在进程内只解析一次 ──────

@lru_cache(maxsize=64)
def cached_parse(path: str) -> WorkflowManifest:
    return parse_manifest(Path(path))

Schema 漂移防护：解析后对 StepDefinition 中每个 raw_params 键名进行 hash 指纹计算，写入 state_store。下次恢复时若指纹不匹配，强制触发 [CONFIRM] 提示用户工作流已变更。

1.2 runner.py — 异步控制循环
设计目标：作为整个执行链路的总调度器，维护 State 对象，按序驱动步骤执行，处理分支、子工作流递归调用、以及所有控制流异常路由。
State 对象定义
pythonfrom dataclasses import dataclass, field
from typing import Any, Dict
import uuid

@dataclass
class RunState:
    run_id:       str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id:  str = ""
    variables:    Dict[str, Any] = field(default_factory=dict)
    current_step: int = 0
    status:       str = "running"   # running | paused | done | failed
主控循环
pythonimport asyncio
from engine.parser    import cached_parse, inject_variables
from engine.state_store import StateStore
from engine.error_policy import resolve_policy, FailureAction
from skills.atomic    import load_skill

class Runner:
    def __init__(self, db_path: str = ".agent/state.db"):
        self.store = StateStore(db_path)

    async def run(self, workflow_id: str, inputs: Dict, run_id: str = None) -> RunState:
        manifest = cached_parse(_resolve_path(workflow_id))
        state    = RunState(workflow_id=workflow_id, variables=inputs)
        if run_id:
            state.run_id = run_id
            state.current_step = await self.store.resume_from(run_id)
            state.variables = await self.store.load_variables(run_id)

        await self.store.init_run(state.run_id, workflow_id)

        for step in manifest.steps[state.current_step:]:
            state.current_step = step.index

            # ── 条件跳过 ────────────────────────────────
            if step.condition and not _eval_condition(step.condition, state.variables):
                await self.store.mark(state.run_id, step.index, "skipped")
                continue

            # ── 子工作流递归 ────────────────────────────
            if step.sub_workflow:
                sub_inputs  = inject_variables(step.raw_params, state.variables)
                sub_outputs = await self.run(step.sub_workflow, sub_inputs)
                state.variables.update(sub_outputs.variables)
                await self.store.mark(state.run_id, step.index, "done", sub_outputs.variables)
                continue

            # ── DANGER 强制人工确认 ──────────────────────
            if "DANGER" in step.flags:
                approved = await _invoke_confirm(
                    f"[DANGER] Step {step.index}「{step.title}」包含危险操作，是否继续？"
                )
                if not approved:
                    await self.store.mark(state.run_id, step.index, "aborted")
                    state.status = "failed"
                    return state

            # ── CONFIRM 人工确认点 ───────────────────────
            if "CONFIRM" in step.flags:
                approved = await _invoke_confirm(f"[CONFIRM] 请确认步骤：{step.title}")
                if not approved:
                    await self.store.mark(state.run_id, step.index, "aborted")
                    state.status = "paused"
                    return state

            # ── 执行技能 ─────────────────────────────────
            params  = inject_variables(step.raw_params, state.variables)
            result  = await _execute_with_policy(step, params)

            if result.success:
                if isinstance(result.output, dict):
                    state.variables.update(result.output)
                elif len(step.outputs) == 1:
                    state.variables[step.outputs[0]] = result.output
                await self.store.mark(state.run_id, step.index, "done", result.output)
            else:
                # 错误路由交由 error_policy 处理
                action = await _handle_failure(step, params, result, state, self.store)
                if action == FailureAction.ROLLBACK:
                    state.status = "failed"
                    return state

        state.status = "done"
        return state

# ── 幽灵任务清理：进程意外中断时标记 running 步骤为 aborted ──

async def cleanup_ghost_runs(store: StateStore, timeout_seconds: int = 3600):
    await store.abort_stale_runs(timeout_seconds)
文件锁死锁保护
python# runner 启动时注册 SIGTERM/SIGINT handler，确保锁被释放
import signal, sys
from filelock import FileLock

_active_locks: list = []

def _register_lock(lock: FileLock):
    _active_locks.append(lock)

def _cleanup_on_exit(sig, frame):
    for lock in_active_locks:
        try: lock.release()
        except: pass
    sys.exit(0)

signal.signal(signal.SIGTERM, _cleanup_on_exit)
signal.signal(signal.SIGINT,_cleanup_on_exit)

1.3 state_store.py — SQLite 持久化层
pythonimport aiosqlite, json, time
from typing import Any, Dict, Optional

class StateStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_run(self, run_id: str, workflow_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS step_states (
                    run_id       TEXT NOT NULL,
                    step_index   INTEGER NOT NULL,
                    skill_name   TEXT,
                    status       TEXT,    -- pending/running/done/failed/skipped/aborted
                    input_json   TEXT,
                    output_json  TEXT,
                    error_msg    TEXT,
                    ts_start     REAL,
                    ts_end       REAL,
                    PRIMARY KEY (run_id, step_index)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS run_meta (
                    run_id      TEXT PRIMARY KEY,
                    workflow_id TEXT,
                    var_snapshot TEXT,  -- 最新变量快照（JSON）
                    ts_created  REAL,
                    ts_updated  REAL
                )
            """)
            await db.execute(
                "INSERT OR IGNORE INTO run_meta VALUES (?,?,?,?,?)",
                (run_id, workflow_id, "{}", time.time(), time.time())
            )
            await db.commit()

    async def mark(self, run_id: str, step_index: int,
                   status: str, output: Any = None, error: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO step_states
                (run_id, step_index, status, output_json, error_msg, ts_end)
                VALUES (?,?,?,?,?,?)
            """, (run_id, step_index, status,
                  json.dumps(output, ensure_ascii=False) if output else None,
                  error, time.time()))
            # 同步更新变量快照到 run_meta
            if output and isinstance(output, dict):
                await db.execute("""
                    UPDATE run_meta SET var_snapshot=json_patch(var_snapshot,?), ts_updated=?
                    WHERE run_id=?
                """, (json.dumps(output), time.time(), run_id))
            await db.commit()  # 每步立即提交，消除崩溃窗口

    async def resume_from(self, run_id: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT MAX(step_index) FROM step_states WHERE run_id=? AND status='done'",
                (run_id,)
            )
            row = await cur.fetchone()
        return (row[0] + 1) if row[0] is not None else 0

    async def load_variables(self, run_id: str) -> Dict:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT var_snapshot FROM run_meta WHERE run_id=?", (run_id,)
            )
            row = await cur.fetchone()
        return json.loads(row[0]) if row else {}

    async def abort_stale_runs(self, timeout_sec: int):
        """将超时仍处于 running 状态的幽灵步骤标记为 aborted"""
        cutoff = time.time() - timeout_sec
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE step_states SET status='aborted'
                WHERE status='running' AND ts_start < ?
            """, (cutoff,))
            await db.commit()

1.4 error_policy.py — 错误策略路由
pythonfrom enum import Enum
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential

class FailureAction(Enum):
    RETRY    = "retry"
    CONFIRM  = "confirm"
    ROLLBACK = "rollback"
    SKIP     = "skip"

@dataclass
class ErrorPolicy:
    max_retries:       int   = 3
    backoff_base:      float = 2.0
    action_on_exhaust: FailureAction = FailureAction.CONFIRM

DEFAULT_POLICIES = {
    "file_reader":    ErrorPolicy(3, 2.0, FailureAction.CONFIRM),
    "file_writer":    ErrorPolicy(2, 2.0, FailureAction.ROLLBACK),
    "shell_executor": ErrorPolicy(2, 2.0, FailureAction.CONFIRM),
    "llm_prompt_call":ErrorPolicy(2, 3.0, FailureAction.CONFIRM),
    "http_client":    ErrorPolicy(3, 2.0, FailureAction.CONFIRM),
    "git_operator":   ErrorPolicy(1, 1.0, FailureAction.ROLLBACK),
    "DANGER":         ErrorPolicy(0, 0.0, FailureAction.ROLLBACK),
}

def resolve_policy(step) -> ErrorPolicy:
    """优先使用 .step.md frontmatter 中的局部覆盖配置"""
    if "DANGER" in step.flags:
        return DEFAULT_POLICIES["DANGER"]
    override = step.raw_params.get("error_policy")
    if override:
        return ErrorPolicy(**override)
    return DEFAULT_POLICIES.get(step.skill_name, ErrorPolicy())

async def _handle_failure(step, params, result, state, store) -> FailureAction:
    policy = resolve_policy(step)
    # tenacity 重试（仅 L0/L1 且 max_retries > 0）
    if policy.max_retries > 0 and step.idempotency in ("L0", "L1"):
        try:
            retried = await_retry_skill(step, params, policy)
            if retried.success:
                state.variables.update(retried.output or {})
                await store.mark(state.run_id, step.index, "done", retried.output)
                return FailureAction.RETRY
        except Exception:
            pass

    # 重试耗尽后按 action_on_exhaust 处理
    if policy.action_on_exhaust == FailureAction.ROLLBACK:
        skill = load_skill(step.skill_name)
        snapshot = await store.load_variables(state.run_id)
        await skill.rollback(params, snapshot)
        await store.mark(state.run_id, step.index, "failed", error=result.error)
        return FailureAction.ROLLBACK

    if policy.action_on_exhaust == FailureAction.CONFIRM:
        approved = await _invoke_confirm(
            f"步骤「{step.title}」失败（{result.error}），是否跳过继续？"
        )
        if approved:
            await store.mark(state.run_id, step.index, "skipped")
            return FailureAction.SKIP

    return FailureAction.ROLLBACK

1.5 context_manager.py — 上下文窗口管理器（补强）
背景：当工作流步骤数量超过 10 步时，累积的 input_json + output_json 总量可能超出 LLM 单次调用的上下文窗口限制，导致 prompt 截断。
pythonimport json
from engine.state_store import StateStore

class ContextManager:
    """
    策略：
    - 保留当前步骤的前 2 步完整输入输出（热区）
    - 更早的步骤通过 llm_prompt_call 压缩为摘要，仅保留关键变量
    - 压缩摘要缓存于 run_meta.var_snapshot，避免重复压缩
    """
    HOT_WINDOW = 2  # 保留完整记录的步骤数

    def __init__(self, store: StateStore):
        self.store = store

    async def get_context_for_step(self, run_id: str, current_index: int) -> dict:
        """返回当前步骤可用的变量上下文，已按窗口策略裁剪"""
        all_vars = await self.store.load_variables(run_id)
        hot_steps = await self.store.load_recent_steps(run_id, self.HOT_WINDOW)

        # 将热区步骤的输入输出完整注入
        context = dict(all_vars)
        for step in hot_steps:
            if step["output_json"]:
                output = json.loads(step["output_json"])
                context.update(output)
        return context

    async def compress_cold_steps(self, run_id: str, current_index: int):
        """对 HOT_WINDOW 之前的步骤进行 LLM 摘要压缩"""
        if current_index <= self.HOT_WINDOW:
            return
        cold_steps = await self.store.load_steps_before(
            run_id, current_index - self.HOT_WINDOW
        )
        if not cold_steps:
            return

        # 构造压缩 prompt
        summary_prompt = (
            "以下是工作流早期步骤的执行记录，请提取最关键的结果变量，"
            "以 JSON 格式返回，丢弃中间过程数据：\n"
            + json.dumps(cold_steps, ensure_ascii=False)
        )
        from skills.atomic.llm_prompt_call import execute as llm_call
        result = await llm_call({"prompt": summary_prompt, "max_tokens": 512})
        if result.success:
            compressed = json.loads(result.output)
            await self.store.patch_variables(run_id, compressed)

1.6 secrets_vault.py — 敏感信息保险箱（补强）
pythonimport os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()  # 从 .env 加载加密变量

class SecretsVault:
    """
    使用规则：
    1. .env 中存储加密后的 API Key：OPENAI_KEY_ENC=<fernet_token>
    2. 主密钥 VAULT_MASTER_KEY 通过环境变量或 CI/CD Secret 注入，禁止落盘
    3. Runner 在调用 Skill 前，按 required_secrets 声明动态解密注入
    """
    def __init__(self):
        master = os.environ.get("VAULT_MASTER_KEY")
        if not master:
            raise RuntimeError("VAULT_MASTER_KEY 未设置，拒绝启动")
        self._fernet = Fernet(master.encode())

    def get_secret(self, key: str) -> str:
        enc_val = os.environ.get(f"{key}_ENC")
        if not enc_val:
            raise KeyError(f"找不到加密变量 {key}_ENC")
        return self._fernet.decrypt(enc_val.encode()).decode()

    def inject_for_skill(self, skill_module, params: dict) -> dict:
        """按 skill 声明的 required_secrets 将解密值注入 params"""
        required = getattr(skill_module, "required_secrets", [])
        for secret_key in required:
            params[secret_key] = self.get_secret(secret_key)
        return params

# 示例：skill 声明所需密钥

# skills/atomic/http_client.py

# required_secrets = ["OPENAI_KEY", "GITHUB_TOKEN"]

Part 2 · Skills 原子技能层完整设计
所有原子技能均遵循统一接口协议，以下提供各核心技能的完整实现。

2.1 标准接口协议回顾
pythonfrom dataclasses import dataclass
from typing import Any, Optional

@dataclass
class SkillResult:
    success: bool
    output:  Any
    error:   Optional[str] = None

async def execute(params: dict) -> SkillResult: ...
async def rollback(params: dict, snapshot: dict) -> SkillResult: ...  # 仅 L2 技能需实现

2.2 llm_prompt_call.py — LLM 调用技能
这是使用频率最高的技能，需要处理输出格式校验、JSON 解析保护以及 Persona 注入。
pythonimport os, json, re
from skills.atomic._base import SkillResult

required_secrets = ["LLM_API_KEY"]

async def execute(params: dict) -> SkillResult:
    prompt        = params["prompt"]
    output_schema = params.get("output_schema")      # 期望输出的结构名称
    persona       = params.get("persona", {})        # 从 frontmatter 注入的人格配置
    max_tokens    = params.get("max_tokens", 2048)
    model         = params.get("model", "gpt-4o")

    # ── 构造 system prompt（注入 Persona）────────────────
    system_parts = ["你是一个工作流自动化引擎的执行单元。"]
    if persona.get("role"):
        system_parts.append(f"你的角色定位：{persona['role']}。")
    if persona.get("tone"):
        system_parts.append(f"回应风格：{persona['tone']}。")
    for constraint in persona.get("constraints", []):
        system_parts.append(f"约束：{constraint}")
    if output_schema:
        system_parts.append(
            f"你必须以合法 JSON 格式输出，结构符合 {output_schema} schema，"
            "不要包含任何额外解释或 Markdown 代码块。"
        )

    system = "\n".join(system_parts)

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=params["LLM_API_KEY"])
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=max_tokens,
        )
        raw_output = response.choices[0].message.content.strip()

        # ── 若期望 JSON，则安全解析 ──────────────────────
        if output_schema:
            cleaned = re.sub(r"^```json|```$", "", raw_output, flags=re.MULTILINE).strip()
            parsed  = json.loads(cleaned)
            return SkillResult(success=True, output=parsed)

        return SkillResult(success=True, output=raw_output)

    except json.JSONDecodeError as e:
        return SkillResult(success=False, output=None,
                           error=f"LLM 返回格式非法 JSON：{e}。原始输出：{raw_output[:200]}")
    except Exception as e:
        return SkillResult(success=False, output=None, error=str(e))

2.3 file_writer.py — 文件写入技能（L1，含 rollback）
pythonimport shutil
from pathlib import Path
from skills.atomic._base import SkillResult

async def execute(params: dict) -> SkillResult:
    target_path = Path(params["path"])
    content     = params["content"]
    guard       = params.get("guard")  # L1 guard：文件若已存在则跳过

    # ── L1 Guard 检查 ────────────────────────────────────
    if guard == "skip_if_exists" and target_path.exists():
        return SkillResult(success=True, output={"path": str(target_path), "skipped": True})

    # ── 备份原文件（用于 rollback）───────────────────────
    backup_path = None
    if target_path.exists():
        backup_path = target_path.with_suffix(target_path.suffix + ".bak")
        shutil.copy2(target_path, backup_path)

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return SkillResult(success=True, output={
            "path":        str(target_path),
            "backup_path": str(backup_path) if backup_path else None,
        })
    except Exception as e:
        # 写入失败时自动恢复备份
        if backup_path and backup_path.exists():
            shutil.copy2(backup_path, target_path)
        return SkillResult(success=False, output=None, error=str(e))

async def rollback(params: dict, snapshot: dict) -> SkillResult:
    """恢复备份文件，删除新写入的文件"""
    target_path = Path(params["path"])
    backup_path = snapshot.get("backup_path")
    try:
        if backup_path and Path(backup_path).exists():
            shutil.copy2(backup_path, target_path)
            Path(backup_path).unlink()
            return SkillResult(success=True, output={"restored": str(target_path)})
        elif target_path.exists():
            target_path.unlink()
            return SkillResult(success=True, output={"deleted": str(target_path)})
    except Exception as e:
        return SkillResult(success=False, output=None, error=str(e))

2.4 shell_executor.py — Shell 执行技能（含 [DANGER] 防护）
pythonimport asyncio, shlex
from skills.atomic._base import SkillResult

# Runner 会在执行前检测 [DANGER] 标识并强制 user_confirm

# 此处追加二次防护：关键字黑名单

_DANGER_PATTERNS = ["rm -rf", "rmdir", "DROP TABLE", "git reset --hard", "shutdown", "mkfs"]

async def execute(params: dict) -> SkillResult:
    cmd         = params["cmd"]
    timeout_sec = params.get("timeout", 60)
    workdir     = params.get("cwd", ".")

    # ── 二次安全检查 ─────────────────────────────────────
    for pattern in _DANGER_PATTERNS:
        if pattern in cmd:
            return SkillResult(success=False, output=None,
                               error=f"命令包含危险模式 [{pattern}]，已被 shell_executor 拦截。"
                                     "请通过 [DANGER] 标识显式确认后执行。")

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        if proc.returncode == 0:
            return SkillResult(success=True, output={
                "stdout":      stdout.decode(),
                "returncode":  0,
            })
        else:
            return SkillResult(success=False, output={"stdout": stdout.decode()},
                               error=stderr.decode())
    except asyncio.TimeoutError:
        proc.kill()
        return SkillResult(success=False, output=None,
                           error=f"命令执行超时（>{timeout_sec}s）")
    except Exception as e:
        return SkillResult(success=False, output=None, error=str(e))

2.5 user_confirm.py — 人工介入安全闸
pythonimport asyncio, sys
from skills.atomic._base import SkillResult

async def execute(params: dict) -> SkillResult:
    message    = params.get("message", "请确认是否继续？")
    timeout    = params.get("timeout_seconds", 300)  # 默认 5 分钟等待
    choices    = params.get("choices", ["yes", "no"])

    # ── 适配不同运行环境 ─────────────────────────────────
    # 1. VS Code 扩展环境：通过 IPC 向 Agent 发送确认请求
    # 2. CLI 环境：直接读取标准输入
    if _is_vscode_env():
        return await _confirm_via_ipc(message, choices, timeout)
    else:
        return await _confirm_via_stdin(message, choices, timeout)

async def _confirm_via_stdin(message, choices, timeout) -> SkillResult:
    prompt_str = f"\n[CONFIRM] {message}\n输入 {'/'.join(choices)}: "
    sys.stdout.write(prompt_str)
    sys.stdout.flush()
    try:
        loop   = asyncio.get_event_loop()
        answer = await asyncio.wait_for(
            loop.run_in_executor(None, input), timeout=timeout
        )
        approved = answer.strip().lower() in ("yes", "y", "确认", "继续")
        return SkillResult(success=True, output={"approved": approved, "answer": answer.strip()})
    except asyncio.TimeoutError:
        return SkillResult(success=False, output={"approved": False},
                           error=f"确认超时（>{timeout}s），自动拒绝")

async def _confirm_via_ipc(message, choices, timeout) -> SkillResult:
    """向 VS Code Extension Host 发送确认请求并等待响应"""
    import json
    # 通过 stdout 输出结构化事件，由 Extension 捕获并展示 UI
    event = json.dumps({"type": "CONFIRM_REQUEST", "message": message, "choices": choices})
    print(f"__AGENT_EVENT__{event}__AGENT_EVENT__", flush=True)
    # 等待 Extension 回写确认结果（通过 stdin 或临时文件）
    # ... 具体实现依赖 Extension 协议
    return SkillResult(success=True, output={"approved": True})  # 占位实现

def _is_vscode_env() -> bool:
    return "VSCODE_PID" in __import__("os").environ

2.6 registry_manager.py — 注册表管理技能
pythonimport json
from pathlib import Path
from filelock import FileLock
from skills.atomic._base import SkillResult

INDEX_PATH = Path(".agent/workflows/index.json")
LOCK_PATH  = Path(".agent/workflows/index.lock")

async def execute(params: dict) -> SkillResult:
    action      = params.get("action", "register")  # register | unregister | query
    workflow_id = params["workflow_id"]

    if action == "register":
        return await _register(workflow_id, params)
    elif action == "unregister":
        return await _unregister(workflow_id)
    elif action == "query":
        return await _query(workflow_id)

async def _register(workflow_id: str, params: dict) -> SkillResult:
    entry = {
        "path":        params["step_file_path"],
        "description": params.get("description", ""),
        "version":     params.get("version", "1.0"),
        "entry_path":  params.get("entry_path", ""),
        "created_at":  __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        with FileLock(str(LOCK_PATH), timeout=10):
            data = json.loads(INDEX_PATH.read_text()) if INDEX_PATH.exists() else {}
            if workflow_id in data:
                # 版本冲突检测：版本号必须递增
                old_ver = tuple(int(x) for x in data[workflow_id]["version"].split("."))
                new_ver = tuple(int(x) for x in entry["version"].split("."))
                if new_ver <= old_ver:
                    return SkillResult(success=False, output=None,
                                       error=f"版本号 {entry['version']} 必须大于已注册版本 {data[workflow_id]['version']}")
            data[workflow_id] = entry
            INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return SkillResult(success=True, output={"registered": workflow_id, "entry": entry})
    except Exception as e:
        return SkillResult(success=False, output=None, error=str(e))

Part 3 · 元子工作流完整流程设计
以下将原设计文档中已有的元子工作流步骤进行补全，重点补充变量数据流和异常处理分支。

3.1 workflow_designer.step.md — 完整版
yaml---
id: workflow_designer
version: "1.0"
inputs:

- name: workflow_spec
    type: WorkflowSpec
    required: true
outputs:
- name: step_md_source
    type: str
- name: skill_gap_list
    type: list

---

```

**Step 1** — 生成步骤草稿 `[L1]`
```

[Skill: llm_prompt_call]
prompt: |
  你是一名资深后端架构师。
  根据以下需求规格，生成工作流步骤清单：
  {{workflow_spec}}

  每个步骤必须包含：

- title: 步骤标题（动词开头）
- skill: 使用的原子技能名称
- inputs: 输入变量列表
- outputs: 输出变量列表
- idempotency: L0 / L1 / L2
- 若涉及文件删除/外部通信/git push，标记 flags: [DANGER]
- 若涉及文件写入/API POST，标记 flags: [CONFIRM]

output_schema: StepDraft[]
Output: step_drafts

```

> 异常处理：若 LLM 返回 JSON 解析失败，触发 `error_policy` 最多重试 2 次；耗尽后触发 `[CONFIRM]` 让用户选择重新描述需求或手动编辑草稿。

**Step 2** — 技能覆盖度检查 `[L0]`
```

[Skill: file_reader]
Input: ".agent/skills/atomic/" -> skill_list

# 读取 skills/atomic/ 目录下所有 .py 文件名，提取技能名称列表

Output: skill_list

```

**Step 3** — 计算技能缺口 `[L0]`
```

[Skill: llm_prompt_call]
prompt: |
  已有技能列表：{{skill_list}}
  步骤草稿所需技能：从 {{step_drafts}} 中提取所有 skill 字段

  请列出：

  1. 缺失的技能名称
  2. 每个缺失技能的建议实现方式（继承自哪个现有技能，或从零编写）

output_schema: SkillGap[]
Output: skill_gap_list

```

**Step 4** — 生成 `.step.md` 源码 `[L1]`
```

[Skill: llm_prompt_call]
prompt: |
  将以下步骤草稿渲染为符合系统规范的 .step.md 源码：
  {{step_drafts}}

  格式规范：

- frontmatter 包含 id, version, inputs, outputs
- 每个步骤以 "## Step N: 标题" 开头
- 声明 idempotency 等级
- 用 [Skill: xxx] 声明技能
- 用 {{变量名}} 引用上下文变量
- 输出变量用 "Output: 变量名" 声明
- 危险操作标记 [DANGER]，需确认操作标记 [CONFIRM]

output_schema: StepMdSource
Output: step_md_source

3.2 security_validator.step.md — 完整版
yaml---
id: security_validator
version: "1.0"
inputs:

- name: step_md_source
    type: str
    required: true
- name: inline_scripts_path
    type: str
    required: false
outputs:
- name: step_md_source_secured
    type: str
- name: security_report
    type: dict

---

```

**Step 1** — 提取操作清单 `[L0]`
```

[Skill: llm_prompt_call]
prompt: |
  从以下 .step.md 源码中提取所有可能产生副作用的操作：
  {{step_md_source}}

  分类提取：

  1. shell_commands: 所有 cmd 字段的 Shell 命令
  2. file_operations: 所有文件写入/删除路径
  3. network_calls: 所有 HTTP 请求（method + url 模板）
  4. external_apis: 所有第三方 API 调用

output_schema: OperationList
Output: operation_list

```

**Step 2** — Bandit 静态扫描（如有内联脚本）`[L0]`
```

[Skill: shell_executor]
condition: "{{inline_scripts_path}} != null"
cmd: bandit -r {{inline_scripts_path}} -f json -o /tmp/bandit_report.json
Output: bandit_report

```

> 若 `inline_scripts_path` 为空，此步骤自动跳过，`bandit_report` 设为空对象。

**Step 3** — 危险操作分级标注 `[L0]`
```

[Skill: llm_prompt_call]
prompt: |
  根据以下信息对每个操作进行风险分级：
  操作清单：{{operation_list}}
  Bandit 报告：{{bandit_report}}

  危险关键词（自动标 [DANGER]）：
  rm, rmdir, shutil.rmtree, DROP TABLE, DELETE FROM,
  git push, git reset --hard, subprocess, os.system, shutdown

  需确认关键词（自动标 [CONFIRM]）：
  file_writer, git_commit, http POST/PUT/PATCH,
  deploy, publish, send_email

  输出每个操作的：operation_id, risk_level(safe/needs_confirm/dangerous), reason

output_schema: RiskLabel[]
Output: risk_labels

```

**Step 4** — 植入安全标识 `[L1]`
```

[Skill: llm_prompt_call]
prompt: |
  根据风险标注结果，修改 .step.md 源码，在对应步骤标题行末尾插入标识：

- needs_confirm → 追加 [CONFIRM]
- dangerous     → 追加 [DANGER]

  风险标注：{{risk_labels}}
  原始源码：{{step_md_source}}

  要求：

  1. 仅修改步骤标题行，不改动步骤内容
  2. 若步骤已有对应标识，不重复添加
  3. 返回完整修改后的 .step.md 字符串

Output: step_md_source_secured

```

**Step 5** — 死循环检测 `[L0]`
```

[Skill: llm_prompt_call]
prompt: |
  分析以下工作流的控制流结构，检测是否存在潜在死循环：
  {{step_md_source_secured}}

  检测规则：

  1. 是否存在步骤 A 依赖步骤 B 的输出，而步骤 B 又依赖步骤 A 的输出（循环依赖）
  2. 是否存在条件分支，其条件永远无法满足终止条件
  3. 是否存在子工作流相互递归调用

  输出：{ "has_loop": bool, "loop_description": str, "affected_steps": [int] }

Output: loop_check_result

```

> 若 `loop_check_result.has_loop == true`，Runner 检测到该输出后将整个流程置为 `failed`，并向用户报告受影响的步骤，拒绝注册。

**Step 6** — 安全报告输出 `[L0]`
```

[Skill: log_recorder]
Input: risk_labels, loop_check_result, bandit_report

# 结构化写入 logs/security_<run_id>.json

Output: security_report

```

---

### 3.3 `registry_manager.step.md` — 完整版（补充版本冲突与原子写入）

在原有设计基础上，补充以下关键细节：

**Step 2 写入 .step.md 文件**：`file_writer` 先写入临时文件 `workflows/dev/{{file_name}}.step.md.tmp`，校验文件完整性（MD5 校验和）后再原子重命名为正式路径，避免写入中途崩溃产生的残缺文件。
```

[Skill: file_writer]
guard: "skip_if_exists"
Input: step_md_source_secured -> "workflows/dev/{{file_name}}.step.md"
atomic_write: true   # 先写 .tmp，校验后重命名
Output: step_file_path

```

**Step 5 更新 index.json**：内置版本号单调递增校验（见 `registry_manager.py` 实现），防止旧版本覆盖新版本。

---

### 3.4 `unit_test_generator.step.md` — 补充测试质量门禁

在原有 5 步基础上，追加一步**质量门禁检查**：

**Step 6** — 测试覆盖率门禁 `[L0]`
```

[Skill: shell_executor]
cmd: |
  pytest {{test_file_path}} -v --tb=short \
    --cov=.agent/skills/atomic \
    --cov=.agent/engine \
    --cov-report=json:/tmp/coverage_{{workflow_id}}.json \
    --cov-fail-under=70
Output: coverage_result

```

> 若覆盖率低于 70%，Runner 不会阻止注册，但会在最终报告中以 `⚠️ 警告` 方式标出，并建议用户补充边界用例。这一设计选择"软门禁"而非"硬阻断"，保证自动生成流程的鲁棒性。

---

### 3.5 元子工作流变量数据流总览
```

用户请求
    │
    ▼
META_CREATOR Step 1：user_request ──► workflow_spec
                                           │
    ┌──────────────────────────────────────┘
    ▼
workflow_designer：workflow_spec ──► step_md_source, skill_gap_list
                                           │
    ┌──────────────────────────────────────┘
    ▼
security_validator：step_md_source ──► step_md_source_secured, security_report
                                           │
    ┌──────────────────────────────────────┘
    ▼
registry_manager：step_md_source_secured ──► workflow_id, entry_path
                                           │
    ┌──────────────────────────────────────┘
    ▼
unit_test_generator：step_md_source_secured + workflow_id ──► test_results
                                           │
    ┌──────────────────────────────────────┘
    ▼
report_generator：workflow_id + test_results + workflow_spec ──► report
每一步的输出变量通过 RunState.variables 字典向下传递，inject_variables() 在运行时完成 {{占位符}} 替换，state_store 在每步完成后持久化变量快照以支持崩溃恢复。

Part 4 · 模块间接口契约汇总
调用方被调用方传入返回RunnerParser.step.md 路径WorkflowManifestRunnerStateStorerun_id, step_index, status无（副作用）RunnerSkillModuleparams: dictSkillResultRunnerRunner（递归）workflow_id, inputsRunStateRunnerContextManagerrun_id, current_indexcontext: dictRunnerSecretsVaultskill_module, paramsparams（注入密钥后）SkillModuleErrorPolicystep: StepDefinitionErrorPolicyRegistryManagerFileLockindex.lock 路径持有锁期间独占写入

至此，Engine 引擎层、Skills 原子技能层、元子工作流层三大核心模块的设计思路与内部脚本/流程均已完整展开。整体遵循"声明在 .step.md、调度在 runner.py、执行在 skills/、持久化在 state_store.py"的分层原则，各层职责边界清晰，可独立测试和演进。
