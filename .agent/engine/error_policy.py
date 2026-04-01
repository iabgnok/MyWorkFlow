from enum import Enum
from dataclasses import dataclass
import asyncio
import logging
import inspect

logger = logging.getLogger(__name__)

class IdempotencyLevel(Enum):
    L0 = "L0"  # 强幂等 (Strong idempotent)：无副作用，可安全自动重试（如：读文件、纯查询计算）
    L1 = "L1"  # 条件幂等 (Conditional idempotent)：执行前需要检查前置条件/guard，确认安全后可重试（如：写文件、Git提交）
    L2 = "L2"  # 非幂等 (Non-idempotent)：不可自动重试，每次执行都会产生新副作用（如：发邮件、删除文件、系统高危修改）

class FailureAction(Enum):
    RETRY    = "retry"      # 继续重试（内部状态，用于循环内）
    CONFIRM  = "confirm"    # 触发人工确认 / 暂停执行
    ROLLBACK = "rollback"   # 执行回退流
    SKIP     = "skip"       # 忽略错误跳过该步骤

@dataclass
class ErrorPolicy:
    max_retries: int = 3
    backoff_base: float = 2.0
    action_on_exhaust: FailureAction = FailureAction.CONFIRM

# 全局默认策略表
DEFAULT_POLICIES = {
    "file_reader":     ErrorPolicy(3, 2.0, FailureAction.CONFIRM),
    "file_writer":     ErrorPolicy(2, 2.0, FailureAction.CONFIRM),
    "llm_prompt_call": ErrorPolicy(2, 3.0, FailureAction.CONFIRM),
    "shell_executor":  ErrorPolicy(0, 0.0, FailureAction.CONFIRM),  # 默认 L2，不自动重试
    "DANGER":          ErrorPolicy(0, 0.0, FailureAction.ROLLBACK),
}

# 技能硬编码的幂等性等级
SKILL_IDEMPOTENCY = {
    "file_reader": IdempotencyLevel.L0,
    "file_writer": IdempotencyLevel.L1,
    "llm_prompt_call": IdempotencyLevel.L0,
    "shell_executor": IdempotencyLevel.L2,
}

from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

def resolve_policy(skill_name: str, step_metadata: dict = None) -> ErrorPolicy:
    """根据技能名和元数据解析具体合并后的错误重试策略"""
    # TODO: 未来可从 step_metadata 中提取 error_policy 进行覆盖，如：yaml 中的 error_policy: {max_retries: 5}
    return DEFAULT_POLICIES.get(skill_name, ErrorPolicy(0, 0.0, FailureAction.CONFIRM))

async def execute_with_policy(skill_name: str, execute_func, *args, **kwargs):
    """
    基于 tenacity 重构的带有 Error Policy 保护框架的技能执行器
    如果是 L0/L1 则依据 max_retries 进行退避重试
    如果是 L2 则强行拦截自动重试机制
    """
    policy = resolve_policy(skill_name)
    level = SKILL_IDEMPOTENCY.get(skill_name, IdempotencyLevel.L2)
    max_retries = policy.max_retries if level in (IdempotencyLevel.L0, IdempotencyLevel.L1) else 0

    if max_retries == 0:
        try:
            if inspect.iscoroutinefunction(execute_func):
                return await execute_func(*args, **kwargs)
            else:
                return await asyncio.to_thread(execute_func, *args, **kwargs)
        except Exception as e:
            logger.error(f"❌ 技能 {skill_name} ({level.value}) 执行失败，不允许重试: {e}")
            raise Exception(f"[{policy.action_on_exhaust.value.upper()}] Skill {skill_name} failed: {e}")

    # L0/L1 启用 tenacity 重试
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_retries + 1),
            wait=wait_exponential(multiplier=policy.backoff_base, min=1, max=30),
            reraise=True # 将实际的异常抛出
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    logger.warning(f"⚠️ 技能 {skill_name} 进行第 {attempt.retry_state.attempt_number - 1}/{max_retries} 次重试...")
                
                if inspect.iscoroutinefunction(execute_func):
                    return await execute_func(*args, **kwargs)
                else:
                    return await asyncio.to_thread(execute_func, *args, **kwargs)
    except Exception as e:
        logger.error(f"🚫 技能 {skill_name} 重试耗尽 (已尝试 {max_retries} 次)，触发耗尽策略配置: {policy.action_on_exhaust.value}")
        raise Exception(f"[{policy.action_on_exhaust.value.upper()}] Skill {skill_name} failed after {max_retries} retries. Cause: {e}")
