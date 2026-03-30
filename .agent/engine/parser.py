import re
import yaml

class WorkflowParser:
    def __init__(self, filepath):
        self.filepath = filepath
        self.raw_content = ""
        self.metadata = {}
        self.steps = []

    def parse(self):
        with open(self.filepath, 'r', encoding='utf-8') as f:
            self.raw_content = f.read()

        # Parse YAML frontmatter
        yaml_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', self.raw_content, re.DOTALL)
        if yaml_match:
            self.metadata = yaml.safe_load(yaml_match.group(1)) or {}
            content_without_frontmatter = self.raw_content[yaml_match.end():]
        else:
            self.metadata = {}
            content_without_frontmatter = self.raw_content

        # Split by ## Step \d+
        # Using positive lookahead so we don't consume the "## Step" in the split output
        # or we can just split and rebuild
        raw_steps = re.split(r'(?m)^## Step\s+\d+', content_without_frontmatter)
        
        # The first chunk is preamble
        preamble = raw_steps[0]
        
        for i, step_content in enumerate(raw_steps[1:], 1):
            step = {
                'id': i,
                'name': self._extract_step_name(step_content),
                'content': step_content.strip(),
                'action': self._extract_action(step_content),
                'inputs': self._extract_io(step_content, 'Input'),
                'outputs': self._extract_io(step_content, 'Output')
            }
            self.steps.append(step)
            
        return {
            'metadata': self.metadata,
            'steps': self.steps
        }

    def _extract_step_name(self, content):
        match = re.search(r'^.*:(.*)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_action(self, content):
        match = re.search(r'\*\*Action\*\*:\s*`?(.*?)`?(?:\n|$)', content)
        if match:
            return match.group(1).strip()
        return "Unknown"

    def _extract_io(self, content, io_type):
        # looks for **Input**: list or similar
        regex = rf'\*\*{io_type}\*\*:\n((?:-.*\n?)*)'
        match = re.search(regex, content)
        if match:
            items = match.group(1).strip().split('\n')
            return [re.sub(r'^- ', '', item).strip() for item in items if item.strip()]
        return []

    @staticmethod
    def replace_variables(text, variables):
        for key, value in variables.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text
