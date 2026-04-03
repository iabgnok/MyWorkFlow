import pytest
import os
from engine.parser import WorkflowParser, WorkflowParseError

def test_missing_file():
    parser = WorkflowParser("non_existent_file.md")
    with pytest.raises(WorkflowParseError, match="Workflow file not found"):
        parser.parse()

def test_invalid_yaml(tmp_path):
    invalid_content = """---
name: [Invalid YAML
---
"""
    test_file = tmp_path / "invalid.md"
    test_file.write_text(invalid_content)
    
    parser = WorkflowParser(str(test_file))
    with pytest.raises(WorkflowParseError, match="Invalid YAML frontmatter"):
        parser.parse()

def test_valid_parsing(tmp_path):
    valid_content = """---
name: "Test workflow"
---
## Step 1
**Name**: Init
**Action**: `llm_prompt_call`
**Input**:
- None
**Output**:
- `res`
"""
    test_file = tmp_path / "valid.md"
    test_file.write_text(valid_content)
    
    parser = WorkflowParser(str(test_file))
    result = parser.parse()
    
    assert result['metadata']['name'] == "Test workflow"
    assert len(result['steps']) == 1
    
    step = result['steps'][0]
    assert step['id'] == 1
    assert step['action'] == "llm_prompt_call"
    
def test_replace_variables():
    text = "Hello {{name}}!"
    variables = {"name": "Alice"}
    result = WorkflowParser.replace_variables(text, variables)
    assert result == "Hello Alice!"
    
    text_dict = "Data: {{data}}"
    variables_dict = {"data": {"key": "value"}}
    result_dict = WorkflowParser.replace_variables(text_dict, variables_dict)
    assert result_dict == 'Data: {"key": "value"}'
