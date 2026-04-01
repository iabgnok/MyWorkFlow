import os

class FileReader:
    def __init__(self):
        pass

    def execute(self, text, context):
        # 从上下文中获取目标文件路径，默认使用 file_path
        # 我们也可以从 text(剧本) 中解析输入变量的映射，但 MVP 里直接从 context 取
        file_path = context.get('file_path')
        if not file_path:
            print("[FileReader] 错误：上下文中未找到 'file_path' 变量。")
            return {}
            
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        print(f"[FileReader] 正在读取文件: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"[FileReader] 成功读取文件内容，共 {len(content)} 字符。")
        
        # 返回提取出的变量，供工作流存入上下文
        return {"file_content": content}
