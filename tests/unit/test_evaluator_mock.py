import pytest
from skills.atomic.llm_evaluator_call import LLMEvaluatorCall
import json

class MockResponse:
    def __init__(self, text):
        self.text = text

class MockModel:
    def __init__(self, text):
        self.text = text
    def generate_content(self, *args, **kwargs):
        return MockResponse(self.text)

class MockClient:
    def __init__(self, text):
        self.models = MockModel(text)

@pytest.fixture
def evaluator():
    return LLMEvaluatorCall()

@pytest.fixture
def sample_text():
    return "```prompt\nYou are a reviewer...\n```"

def test_static_scan(evaluator):
    issues = evaluator.static_regex_scan("os.system('rm -rf /')")
    assert len(issues) > 0
    assert "发现危险命令正则" in issues[0]

def test_evaluator_valid_json(mocker, evaluator, sample_text):
    mocker.patch('google.genai.Client', return_value=MockClient('{"status": "APPROVED", "score": 90}'))
    mocker.patch.dict('os.environ', {'GEMINI_API_KEY': 'fake_key'})
    
    result = evaluator.execute(sample_text, {})
    
    assert "evaluator_report" in result
    report = json.loads(result["evaluator_report"])
    assert report["status"] == "APPROVED"
    assert "__jump_to__" not in result

def test_evaluator_missing_json(mocker, evaluator, sample_text):
    mocker.patch('google.genai.Client', return_value=MockClient("I think the code is great but I forgot to output JSON."))
    mocker.patch.dict('os.environ', {'GEMINI_API_KEY': 'fake_key'})
    
    result = evaluator.execute(sample_text, {'generator_step_id': 3})
    
    assert "__jump_to__" in result
    assert result["__jump_to__"] == 3
    assert "System Fallback" in result["__feedback__"]

def test_evaluator_broken_json(mocker, evaluator, sample_text):
    mocker.patch('google.genai.Client', return_value=MockClient('Here is my review: {"status": "REJECTED", "missing_quote: "}'))
    mocker.patch.dict('os.environ', {'GEMINI_API_KEY': 'fake_key'})
    
    result = evaluator.execute(sample_text, {'generator_step_id': 4})
    
    assert "__jump_to__" in result
    assert result["__jump_to__"] == 4
    assert "JSON Parse Error" in result["evaluator_report"]
    assert "System Fallback" in result["__feedback__"]
