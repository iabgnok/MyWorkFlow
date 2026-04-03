import pytest
import asyncio
import os
from engine.runner import Runner
from engine.state_store import StateStore

class MockSuccessSkill:
    def __init__(self, key="default_key", val="default_val"):
        self.key = key
        self.val = val
        self.call_count = 0

    async def execute(self, text, context):
        self.call_count += 1
        return {self.key: self.val}

class MockFailSkill:
    def __init__(self, fail_times=1):
        self.call_count = 0
        self.fail_times = fail_times

    async def execute(self, text, context):
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise ValueError("Intentional crash")
        return {"recovered": True}

@pytest.fixture
def workflow_file(tmp_path):
    wf_content = """---
name: "Core Runner Test"
---
## Step 1
**Name**: Step 1 Process
**Action**: `mock_step1`
**Input**:
- None
**Output**:
- `var1`

## Step 2
**Name**: Step 2 Process
**Action**: `mock_step2`
**Input**:
- `var1`
**Output**:
- `var2`
"""
    wf_path = tmp_path / "core.step.md"
    wf_path.write_text(wf_content)
    return str(wf_path)

@pytest.mark.asyncio
async def test_runner_happy_path(workflow_file, tmp_path):
    db_path = str(tmp_path / "happy.db")
    runner = Runner(workflow_file, db_path=db_path)
    
    skill1 = MockSuccessSkill("var1", "hello")
    skill2 = MockSuccessSkill("var2", "world")
    runner.skills = {"mock_step1": skill1, "mock_step2": skill2}
    
    result = await runner.run()
    
    assert result["status"] == "success"
    assert result["context"]["var1"] == "hello"
    assert result["context"]["var2"] == "world"
    assert skill1.call_count == 1
    assert skill2.call_count == 1

@pytest.mark.asyncio
async def test_runner_resume_from_state(workflow_file, tmp_path):
    db_path = str(tmp_path / "resume.db")
    run_id = "test_resume_run_1"
    
    # First execution to fail at step 2
    runner1 = Runner(workflow_file, initial_context={"init_var": 0}, db_path=db_path)
    skill1 = MockSuccessSkill("var1", "hello")
    skill2_fail = MockFailSkill(fail_times=1)
    runner1.skills = {"mock_step1": skill1, "mock_step2": skill2_fail}
    
    with pytest.raises(Exception, match="Intentional crash"):
        await runner1.run(run_id=run_id)
        
    assert skill1.call_count == 1
    assert skill2_fail.call_count == 1
    
    # Check DB state
    store = StateStore(db_path)
    await store.connect()
    state = await store.load_run_state(run_id)
    await store.close()
    assert "failed" in state["status"]
    assert state["current_step_id"] == 2
    assert state["context"]["var1"] == "hello"

    # Resume execution
    runner2 = Runner(workflow_file, db_path=db_path)
    skill1_again = MockSuccessSkill("should_not_run", 1)
    skill2_pass = MockSuccessSkill("var2", "world")
    runner2.skills = {"mock_step1": skill1_again, "mock_step2": skill2_pass}
    
    result = await runner2.run(run_id=run_id)
    
    assert result["status"] == "success"
    # Should not call step 1 again
    assert skill1_again.call_count == 0
    assert skill2_pass.call_count == 1
    assert result["context"]["var1"] == "hello"
    assert result["context"]["var2"] == "world"

@pytest.mark.asyncio
async def test_runner_missing_skill(tmp_path):
    wf_content = """---
name: "Missing Skill Test"
---
## Step 1
**Name**: Unknown
**Action**: `not_exist`
"""
    wf_path = tmp_path / "missing.step.md"
    wf_path.write_text(wf_content)
    
    runner = Runner(str(wf_path), db_path=str(tmp_path / "missing.db"))
    runner.skills = {}  # Empty skills
    
    result = await runner.run()
    # Runner skips unknown skills currently
    assert result["status"] == "success"
