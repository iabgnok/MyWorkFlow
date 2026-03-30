import sys
import os

# 将根目录和.agent同时加入环境变量以便可以导入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 因为我们现在目录名是 .agent，Python 默认把 . 当作相对引入的标识，因此直接通过路径操作而不是通过.agent导入
from engine.parser import WorkflowParser
from skills.atomic.llm_prompt_call import LLMPromptCall
from skills.atomic.file_writer import FileWriter
from skills.atomic.file_reader import FileReader
import logging

# 配置日志输出，使用中文提示
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Runner:
    def __init__(self, filepath, initial_context=None):
        self.filepath = filepath
        self.context = initial_context or {}
        self.parser = WorkflowParser(filepath)
        self.skills = {
            'llm_prompt_call': LLMPromptCall(),
            'file_writer': FileWriter(),
            'file_reader': FileReader()
        }

    def run(self):
        parsed = self.parser.parse()
        steps = parsed['steps']
        
        logger.info(f"🚀 开始执行工作流 [{parsed['metadata'].get('name', 'UNKNOWN')}], 总计包含 {len(steps)} 个步骤。")
        logger.info(f"🔧 初始上下文变量 (Context): {self.context}")
        
        for step in steps:
            logger.info(f"▶️ [执行步骤 {step['id']}]: {step['name']} | 使用技能: {step['action']}")
            
            # 使用简单的 Markdown 解析替换其中的变量 {{var}}
            text_context = self.parser.replace_variables(step['content'], self.context)
            
            skill_name = step['action']
            if skill_name in self.skills:
                skill = self.skills[skill_name]
                try:
                    output = skill.execute(text_context, self.context)
                    # 将执行结果合并更新到上下文变量中，供下游步骤使用
                    if output:
                        logger.info(f"✅ 技能 {skill_name} 执行完毕，输出变量: {list(output.keys())}")
                        self.context.update(output)
                    else:
                        logger.warning(f"⚠️ 技能 {skill_name} 没有返回任何输出。")
                except Exception as e:
                    logger.error(f"❌ 技能 {skill_name} 执行失败: {e}")
            else:
                logger.error(f"❌ 未找到对应注册的技能: '{skill_name}'! 该步骤已被跳过。")

        logger.info("🎉 ---------------- 工作流执行完成 ---------------- 🎉")
        logger.info(f"📦 最终状态/上下文: {self.context.keys()}")
        return self.context

if __name__ == '__main__':
    import os
    # 模拟外部传入输入变量，启动工作流
    print("\n" + "="*50)
    print("=== 开始验证 MVP 第一个工作流流水线 ===")
    print("="*50)
    
    # 如果测试输入文件不存在，才创建一个默认的。否则保留用户自己的修改！
    if not os.path.exists('test_input.txt'):
        with open('test_input.txt', 'w', encoding='utf-8') as f:
            f.write("MyWorkflow 是一个轻量级、不强依赖 AST 解析，且采用“小步快跑”架构的本地 AI Agent 运行框架。\n这篇 MVP 旨在验证全内存下的核心功能运转。")
            
    runner = Runner('.agent/workflows/dev/hello_world.step.md', initial_context={'file_path': 'test_input.txt', 'target_file': 'output.txt'})
    runner.run()

    # 最后验证输出
    try:
        with open('output.txt', 'r', encoding='utf-8') as f:
            print("\n----- 最终 output.txt 的内容 -----")
            print(f.read())
            print("----------------------------------\n")
    except Exception as e:
        print(f"打开输出文件失败: {e}")