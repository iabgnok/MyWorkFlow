class FileWriter:
    def execute(self, text, context):
        import re
        import os
        
        # Look for content and target
        content_match = re.search(r'```content\n(.*?)\n```', text, re.DOTALL)
        if content_match:
            content = content_match.group(1).strip()
            # Replace vars
            for k, v in context.items():
                content = content.replace(f"{{{{{k}}}}}", str(v))
                
            # Assume target_file is passed in context or extracted
            file_path = context.get('target_file', 'output.txt')
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            print(f"File updated at {file_path}")
            return {"file_writer_status": "Success"}
        return {}
