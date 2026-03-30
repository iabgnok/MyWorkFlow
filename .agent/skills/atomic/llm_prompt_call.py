class LLMPromptCall:
    def __init__(self):
        pass

    def execute(self, text, context):
        import re
        import os
        
        # 尝试寻找 Prompt 代码块
        prompt_match = re.search(r'```prompt\n(.*?)\n```', text, re.DOTALL)
        if prompt_match:
            prompt = prompt_match.group(1).strip()
            # 替换上下文变量
            for k, v in context.items():
                prompt = prompt.replace(f"{{{{{k}}}}}", str(v))
            
            # 使用 Google Gemini API
            try:
                from dotenv import load_dotenv
                load_dotenv() # 加载当前目录下的 .env 文件
                
                api_key = os.environ.get("GEMINI_API_KEY")
                
                # 配置代理，解决国内直连报错 grpc_status:14 无法连接的问题
                http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
                https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
                
                if api_key:
                    from google import genai
                    from google.genai import types
                    import httpx
                    
                    # 优先使用代理配置构建 Client
                    if http_proxy or https_proxy:
                        print(f"🔧 [LLMPromptCall] 检测到代理配置: http={http_proxy}, https={https_proxy}，正在为您配置走代理...")
                        client = genai.Client(
                            api_key=api_key,
                            http_options={'api_version': 'v1alpha'} # 如果需要特殊的配置
                        )
                        # 更底层的网络连接问题，如果原生 Client 仍然出错，
                        # 官方建议是在运行命令前设置系统环境变量 HTTP_PROXY 和 HTTPS_PROXY。
                    else:
                        print(f"⚠️ [LLMPromptCall] 未检测到代理配置（HTTP_PROXY）。如果您在国内，这可能会导致下方的连通性连接超时...")
                        client = genai.Client(api_key=api_key)

                    print("🤖 正在调用 Google Gemini 大模型，请稍候...")
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                    )
                    content = response.text
                else:
                    print("⚠️ 未找到 GEMINI_API_KEY，切换到[Mock模拟模式]...")
                    content = f"[这是模拟输出，请在根目录创建 .env 文件并配置 GEMINI_API_KEY]\n提示词原文:\n{prompt}"
                
                return {"llm_output": content}
            except Exception as e:
                print(f"❌ 调用 Google API 时发生错误: {e}")
                return {"llm_output": f"Mock error fallback: {e}"}
        return {}
