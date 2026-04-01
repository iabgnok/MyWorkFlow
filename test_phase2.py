import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.agent')))

from engine.runner import Runner

async def main():
    print("="*50)
    print("=== 开始跑通 Phase 2 Evaluator 循环测试 ===")
    print("="*50)
    
    wf_path = '.agent/workflows/dev/phase2_evaluator_loop.step.md'
    target_output = 'test_phase2_output.py'
    
    # 初始化 context，添加缺省变量值避免 parser 里残留 {{var}}
    initial_context = {
        'target_file': target_output,
        'escalation_level': 0,
        'evaluator_feedback': '无',
        'generator_step_id': 2  # 设置跳回步骤号为步骤 2（即 Generator 输出环节）
    }
    
    # 删除之前可能残留的状态或输出
    if os.path.exists(target_output):
        os.remove(target_output)
    
    runner = Runner(wf_path, initial_context=initial_context)
    
    try:
        result = await runner.run()
        print(f"\n✅ 任务运行结果 Run_id: {result['run_id']} - 状态: {result['status']}")
        
        if os.path.exists(target_output):
            print("\n----- 最终生成的纯净源码 -----")
            with open(target_output, "r", encoding="utf-8") as f:
                print(f.read())
            print("------------------------------\n")
        else:
            print("⚠️ 未生成目标文件，可能被安全机制彻底阻断或失败。")
            
    except Exception as e:
        print(f"\n❌ 执行被中断或报错: {e}")

if __name__ == '__main__':
    asyncio.run(main())
