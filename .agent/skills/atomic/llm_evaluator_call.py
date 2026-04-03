from google import genai
import logging
import json
import re
import os

logger = logging.getLogger(__name__)

class LLMEvaluatorCall:
    def __init__(self):
        pass

    def static_regex_scan(self, code_text):
        """静态安全扫描，拦截危险的高危命令"""
        dangerous_patterns = [
            r'\brm\s+-rf\b',
            r'\bDROP\s+TABLE\b',
            r'\bgit\s+push\s+--force\b',
            r'os\.system\([\'"]rm '
        ]
        issues = []
        for pattern in dangerous_patterns:
            if re.search(pattern, code_text, re.IGNORECASE):
                issues.append(f"发现危险命令正则: {pattern}")
        return issues

    def execute(self, text, context):
        """
        利用大语言模型作为 Evaluator 的独立节点。
        检查生成的 output (Handoff Artifact)，如果合原则返回 APPROVED，不合原则输出反馈，返回跃迁参数。
        """
        static_issues = self.static_regex_scan(text)
        
        # 解析用户的评估要求prompt
        eval_prompt_match = re.search(r'```prompt\n(.*?)\n```', text, re.DOTALL)
        if eval_prompt_match:
            sys_prompt = eval_prompt_match.group(1).strip()
            
            # 使用 LLM 进行 4 维指标评分
            try:
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.environ.get("GEMINI_API_KEY")
                
                http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
                https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
                
                if api_key:
                    if http_proxy or https_proxy:
                        client = genai.Client(
                            api_key=api_key,
                            http_options={'api_version': 'v1alpha'}
                        )
                    else:
                        client = genai.Client(api_key=api_key)
                        
                    escalation_level = context.get('escalation_level', 0)
                    # 动态注入当前评价宽容度，R3 会放宽标准
                    relaxation = "你当前的标准已在 R3，允许放宽工程健壮性和角色约束度，只要逻辑闭环且无安全问题即可通过。" if escalation_level >= 3 else "你需要严格考察 1.逻辑完备性 2.安全 3.工程健壮性 4.角色约束度。"
                    
                    full_prompt = f"""
{sys_prompt}
==============
{relaxation}

请你按照以下 JSON 格式输出评估结果 (只返回 JSON)
如果发现有缺陷，status必须为 REJECTED。如果包含静态危险代码，必须为 REJECTED 并标注 defect。
静态安全发现的强制问题: {static_issues if static_issues else '无'}

期望的 JSON 输出格式：
{{
  "status": "APPROVED", // 或者 "REJECTED"
  "score": 90,
  "defects": [
    {{"location": "坐标", "reason": "原因说明"}}
  ],
  "overall_feedback": "详细说明"
}}
"""
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=full_prompt,
                    )
                    
                    output_text = response.text
                    
                    # 尝试解析 JSON
                    target_step = context.get('generator_step_id', 2)
                    json_str_match = re.search(r'\{.*\}', output_text, re.DOTALL)
                    if json_str_match:
                        try:
                            eval_json = json.loads(json_str_match.group(0))
                        except json.JSONDecodeError as e:
                            logger.warning(f"⚠️ Evaluator 虽然返回了疑似 JSON，但格式受损无法解析: {e}。强制执行 Fallback 降级重试。")
                            return {
                                "evaluator_report": '{"status": "REJECTED", "reason": "JSON Parse Error"}',
                                "__jump_to__": target_step,
                                "__feedback__": f"[System Fallback] 上次你返回的审查报告格式损坏 (无法被解析为标准的 JSON)：{e}，请严格按照要求的 JSON 格式输出。"
                            }

                        logger.info(f"🧐 Evaluator 评审结果: {eval_json.get('status', 'UNKNOWN')} 给出分数: {eval_json.get('score', 0)}")
                        
                        if eval_json.get("status") == "REJECTED":
                            return {
                                "evaluator_report": json.dumps(eval_json, ensure_ascii=False),
                                "__jump_to__": target_step,
                                "__feedback__": str(eval_json.get("defects", [])) + " | " + str(eval_json.get("overall_feedback", ""))
                            }
                        else:
                            return {
                                "evaluator_report": json.dumps(eval_json, ensure_ascii=False)
                            }
                    else:
                        logger.warning(f"⚠️ Evaluator 的返回没有包含正常的 JSON: {output_text[:100]}... 强制执行 Fallback 降级重试。")
                        return {
                            "evaluator_report": '{"status": "REJECTED", "reason": "No JSON match"}',
                            "__jump_to__": target_step,
                            "__feedback__": "[System Fallback] 你的上一轮回复中没有发现有效的 JSON 块。系统已对你当前生成的代码自动判定为 REJECTED。请确保返回指定的 JSON 对象包围在 {} 内。"
                        }
            except Exception as e:
                logger.error(f"❌ Evaluator 评估过程 LLM 调用异常: {e}")
                return {"eval_error": str(e)}

        return {}