import aiosqlite
import json
import logging
import copy
from pathlib import Path

logger = logging.getLogger(__name__)

class StateStore:
    def __init__(self, db_path: str = "workflow_state.db"):
        self.db_path = db_path
        self._conn = None

    async def connect(self):
        if not self._conn:
            # 确保数据库所在目录存在
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.db_path)
            await self._init_db()
            logger.info("📦 状态数据库已连接。")

    async def _init_db(self):
        # 初始化运行状态表
        await self._conn.execute('''
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                workflow_name TEXT,
                status TEXT,
                current_step_id INTEGER,
                context TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 初始化步骤执行日志表（可选扩展）
        await self._conn.execute('''
            CREATE TABLE IF NOT EXISTS step_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                step_id INTEGER,
                status TEXT,
                output TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        ''')
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("📦 状态数据库连接已关闭。")

    def _mask_secrets(self, context: dict) -> dict:
        """启发式脱敏，避免 API 密钥等凭据明文落库"""
        safe_context = copy.deepcopy(context)
        sensitive_keywords = {'api_key', 'token', 'secret', 'password', 'credential', 'auth'}
        
        for k, v in safe_context.items():
            if any(sec in k.lower() for sec in sensitive_keywords) and isinstance(v, str):
                safe_context[k] = "******"
            elif isinstance(v, dict):
                # 递归处理嵌套字典
                safe_context[k] = self._mask_secrets(v)
                
        return safe_context

    async def save_run_state(self, run_id: str, workflow_name: str, status: str, current_step_id: int, context: dict):
        """保存任务当前的运行状态"""
        safe_context = self._mask_secrets(context)
        context_str = json.dumps(safe_context, ensure_ascii=False)
        await self._conn.execute('''
            INSERT INTO runs (run_id, workflow_name, status, current_step_id, context)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status,
                current_step_id=excluded.current_step_id,
                context=excluded.context,
                updated_at=CURRENT_TIMESTAMP
        ''', (run_id, workflow_name, status, current_step_id, context_str))
        await self._conn.commit()

    async def load_run_state(self, run_id: str):
        """加载中断的任务状态"""
        async with self._conn.execute('SELECT workflow_name, status, current_step_id, context FROM runs WHERE run_id = ?', (run_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "workflow_name": row[0],
                    "status": row[1],
                    "current_step_id": row[2],
                    "context": json.loads(row[3]) if row[3] else {}
                }
            return None
