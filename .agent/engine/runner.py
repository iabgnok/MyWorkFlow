import sys
import os
import asyncio
import uuid
import logging

# 将根目录和.agent同时加入环境变量以便可以导入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 因为我们现在目录名是 .agent，Python 默认把 . 当作相对引入的标识，因此直接通过路径操作而不是通过.agent导入
from engine.parser import WorkflowParser
from engine.state_store import StateStore
from engine.error_policy import execute_with_policy
from skills.atomic.llm_prompt_call import LLMPromptCall
from skills.atomic.file_writer import FileWriter
from skills.atomic.file_reader import FileReader

# 配置日志输出，使用中文提示
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Runner:
    def __init__(self, filepath, initial_context=None, db_path=None):
        self.filepath = filepath
        self.context = initial_context or {}
        self.parser = WorkflowParser(filepath)
        self.state_store = StateStore(db_path) if db_path else StateStore(os.path.join(os.path.dirname(__file__), 'workflow_state.db'))
        self.skills = {
            'llm_prompt_call': LLMPromptCall(),
            'file_writer': FileWriter(),
            'file_reader': FileReader()
        }

    async def run(self, run_id=None):
        await self.state_store.connect()
        try:
            parsed = self.parser.parse()
            steps = parsed['steps']
            workflow_name = parsed['metadata'].get('name', 'UNKNOWN')
            
            # 使用现有或生成新的 run_id
            current_run_id = run_id or str(uuid.uuid4())
            start_step_id = 1
            
            # 尝试加载之前的状态
            if run_id:
                state = await self.state_store.load_run_state(current_run_id)
                if state:
                    logger.info(f"🔄 找到已存在状态的 run_id: {current_run_id}。从中断步的后一步继续...")
                    self.context.update(state.get("context", {}))
                    # 我们目前从报错的那一步重试或者从它的下一步开始，暂时设定为未完成的 current_step_id 继续
                    start_step_id = state.get("current_step_id", start_step_id)
                else:
                    logger.warning(f"⚠️ 未找到 run_id: {current_run_id} 的状态记录，作为全新任务开始执行...")

            logger.info(f"🚀 开始执行工作流 [{workflow_name}], 总计包含 {len(steps)} 个步骤。 Run ID: {current_run_id}")
            logger.info(f"🔧 当前上下文变量 (Context): {self.context}")
            
            # 更新运行状态（开始）
            await self.state_store.save_run_state(current_run_id, workflow_name, "running", start_step_id, self.context)
            
            for step in steps:
                if step['id'] < start_step_id:
                    logger.info(f"⏭️ [跳过步骤 {step['id']}]: {step['name']} (由于断点恢复)")
                    continue

                logger.info(f"▶️ [执行步骤 {step['id']}]: {step['name']} | 使用技能: {step['action']}")
                
                # 记录即将执行的步骤，一旦崩溃将恢复执行该步骤
                await self.state_store.save_run_state(current_run_id, workflow_name, "running", step['id'], self.context)
                
                text_context = self.parser.replace_variables(step['content'], self.context)
                
                skill_name = step['action']
                if skill_name in self.skills:
                    skill = self.skills[skill_name]
                    try:
                        # 使用 error_policy 包装好的带重试和分类拦截策略的执行逻辑
                        output = await execute_with_policy(skill_name, skill.execute, text_context, self.context)
                        
                        if output:
                            logger.info(f"✅ 技能 {skill_name} 执行完毕，输出变量: {list(output.keys())}")
                            self.context.update(output)
                        else:
                            logger.warning(f"⚠️ 技能 {skill_name} 没有返回任何输出。")
                    except Exception as e:
                        logger.error(f"🔴 技能 {skill_name} 最终由 ErrorPolicy 后向抛出终止异常: {e}")
                        # 发生异常时记录错误状态
                        await self.state_store.save_run_state(current_run_id, workflow_name, f"failed: {e}", step['id'], self.context)
                        raise
                else:
                    logger.error(f"❌ 未找到对应注册的技能: '{skill_name}'! 该步骤已被跳过。")

            # 所有步骤执行成功后
            await self.state_store.save_run_state(current_run_id, workflow_name, "completed", len(steps), self.context)
            logger.info("🎉 ---------------- 工作流执行完成 ---------------- 🎉")
            logger.info(f"📦 最终状态/上下文: {self.context.keys()}")
            
            # 执行成功返回最终 context 或成功状态，以及 run_id
            return {"run_id": current_run_id, "status": "success", "context": self.context}
        finally:
            await self.state_store.close()

if __name__ == '__main__':
    def start_run():
        print("\n" + "="*50)
        print("=== 开始验证 MVP 第一个工作流流水线 (包含断点续传机制和协程化) ===")
        print("="*50)
        
        test_file = 'test_input.txt'
        test_output = 'output.txt'
        
        if not os.path.exists(test_file):
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("MyWorkflow 是一个轻量级、不强依赖 AST 解析，且采用“小步快跑”架构的本地 AI Agent 运行框架。\n这篇 MVP 旨在验证全内存下的核心功能运转。")
                
        # 注意此处的路径可能是相对 main.py 或者 runner.py 的
        # 因为是从 runner.py 运行测试，工作目录可能不同，尝试两种路径找 .step.md
        wf_path = '.agent/workflows/dev/hello_world.step.md'
        if not os.path.exists(wf_path):
            wf_path = '../workflows/dev/hello_world.step.md'
            
        runner = Runner(wf_path, initial_context={'file_path': test_file, 'target_file': test_output})
        
        # 实际执行（使用新版 async），为了演示可恢复性，如果提供 sys.argv[1] 则作为 run_id 从中断处继续
        run_id_arg = sys.argv[1] if len(sys.argv) > 1 else None
        
        result = asyncio.run(runner.run(run_id=run_id_arg))
        print(f"\n✅ 任务运行结果 Run_id: {result['run_id']} - 状态: {result['status']}")

        try:
            with open(test_output, 'r', encoding='utf-8') as f:
                print("\n----- 最终 output.txt 的内容 -----")
                print(f.read())
                print("----------------------------------\n")
        except Exception as e:
            print(f"打开输出文件失败: {e}")

    start_run()