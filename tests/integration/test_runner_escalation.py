import pytest
import asyncio
import os
from engine.runner import Runner
from engine.state_store import StateStore

class MockEvaluatorSkill:
    def __init__(self, target_step=1):
        self.call_count = 0
        self.target_step = target_step

    async def execute(self, text, context):
        self.call_count += 1
        # Always return rejected
        return {
            "evaluator_report": '{"status": "REJECTED"}',
            "__jump_to__": self.target_step,
            "__feedback__": "always bad"
        }

class MockGeneratorSkill:
    async def execute(self, text, context):
        return {"llm_output": "generated code"}

@pytest.mark.asyncio
async def test_escalation_ladder_limit(tmp_path):
    wf_content = """---
name: "Escalation test"
---
## Step 1
**Name**: Gen
**Action**: `mock_gen`
**Input**:
- None
**Output**:
- `code`

## Step 2
**Name**: Eval passes or rejects
**Action**: `mock_eval`
**Input**:
- `code`
**Output**:
- `eval_report`
"""
    wf_path = tmp_path / "escalation.step.md"
    wf_path.write_text(wf_content)
    db_path = tmp_path / "test_escalation.db"
    
    runner = Runner(str(wf_path), db_path=str(db_path))
    runner.skills['mock_gen'] = MockGeneratorSkill()
    runner.skills['mock_eval'] = MockEvaluatorSkill(target_step=1) # Jump back to Gen
    
    # Needs to fail with Escalation Error after 4 rejections
    with pytest.raises(Exception, match=r"步骤 1 的生成被 Evaluator 连续打回 4 次"):
        await runner.run()
        
    assert runner.skills['mock_eval'].call_count == 4
