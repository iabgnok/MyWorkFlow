import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engine.parser import WorkflowParser
from engine.state_store import StateStore
from engine.error_policy import execute_with_policy, DEFAULT_POLICIES, ErrorPolicy, FailureAction

# --- 1. 测试 Parser 变量替换 ---
def test_parser():
    print("--- 1. Testing Parser Variable Replacement ---")
    template = '{ "body": {{my_dict}}, "items": {{my_list}} }'
    context = {
        "my_dict": {"key": "value", "nested": [1, 2]},
        "my_list": [True, False, "Hello"]
    }
    result = WorkflowParser.replace_variables(template, context)
    print(f"Result:\n{result}")
    
    # 验证是否能够被正确的作为 JSON 序列化（以前直接 str() 是带单引号的，无法解析）
    try:
        parsed_json = json.loads(result)
        print("✅ Parser Test Passed: Valid JSON format output.")
    except json.JSONDecodeError as e:
        print(f"❌ Parser Test Failed: {e}")


# --- 2. 测试 StateStore 脱敏落盘 ---
async def test_state_store():
    print("\n--- 2. Testing StateStore Masking ---")
    store = StateStore("test_state.db")
    await store.connect()
    
    dirty_context = {
        "user_name": "Dev",
        "api_key": "sk-123456789",
        "nested_data": {
            "my_password_str": "mypass123",
            "normal_field": 100
        },
        "GCP_CREDENTIAL": "gcp-secret-cert"
    }

    print("Saving dirty context...")
    await store.save_run_state("test-run-1", "test_wf", "running", 1, dirty_context)
    
    loaded_state = await store.load_run_state("test-run-1")
    loaded_context = loaded_state.get("context", {})
    print(f"Loaded Context:\n{json.dumps(loaded_context, indent=2)}")
    
    if loaded_context.get("api_key") == "******" and loaded_context["nested_data"].get("my_password_str") == "******":
         print("✅ StateStore Masking Test Passed.")
    else:
         print("❌ StateStore Masking Test Failed.")

    await store.close()
    if os.path.exists("test_state.db"):
        os.remove("test_state.db")

# --- 3. 测试 ErrorPolicy 结合 Tenacity 回退 ---
async def faulty_skill():
    print("Executing faulty_skill... raising error!")
    raise ValueError("Network Timeout")

async def test_error_policy():
    print("\n--- 3. Testing Error Policy (Tenacity) ---")
    # 强制覆盖测试策略，设置 max_retries=2, base=0.1
    DEFAULT_POLICIES["test_skill"] = ErrorPolicy(max_retries=2, backoff_base=0.1, action_on_exhaust=FailureAction.CONFIRM)
    
    try:
        # 为了测试 tenacity 可以正常重试 2 次加首次 1 次共 3 次
        # 注意此处的技能我们取名为 file_reader (默认存在 L0中) 或者 test_skill我们并没有加在 L0/L1里，
        # 在 error_policy里没有在 L0/L1 的默认是L2 不重试。
        # 我们用 llm_prompt_call 来强制进行 L0 测试
        DEFAULT_POLICIES["llm_prompt_call"] = ErrorPolicy(max_retries=2, backoff_base=0.1, action_on_exhaust=FailureAction.CONFIRM)
        await execute_with_policy("llm_prompt_call", faulty_skill)
    except Exception as e:
        print(f"Caught expected Exception:\n  {e}")
        if "[CONFIRM]" in str(e) and "llm_prompt_call" in str(e):
            print("✅ ErrorPolicy (Tenacity) Test Passed.")
        else:
            print("❌ ErrorPolicy (Tenacity) Test Failed.")

async def main():
    test_parser()
    await test_state_store()
    await test_error_policy()

if __name__ == "__main__":
    asyncio.run(main())