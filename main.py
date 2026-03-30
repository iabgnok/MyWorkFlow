import sys
import os

# 将核心逻辑代理给 .agent.engine.runner
def main():
    print("\n" + "="*50)
    print("=== 开始验证 MVP 第一个工作流流水线 (全新目录架构) ===")
    print("="*50)
    
    # 动态将 .agent 目录注册为包名 "agent"，从而避开以点开头的包导入限制
    agent_dir = os.path.join(os.path.dirname(__file__), ".agent")
    
    # 我们不在代码里使用带点的 .agent，由于底层它是一个文件夹，我们直接添加外层到环境变量，再通过 `importlib` 或者直接 `exec` 方式加载。为了优雅，我们直接运行 .agent/engine/runner.py 脚本。
    runner_script = os.path.join(agent_dir, 'engine', 'runner.py')
    os.system(f'python "{runner_script}"')

if __name__ == "__main__":
    main()