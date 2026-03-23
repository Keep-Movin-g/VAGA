from openai import OpenAI
from config import cfg

class LLMClient:
    """统一的 LLM/VLM 客户端：负责所有大模型通信，绝对禁止混入业务逻辑"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=cfg.LLM_API_KEY,
            base_url=cfg.LLM_BASE_URL
        )

    def chat_with_tools(self, messages: list, tools: list = None, temperature: float = 0.1):
        """支持函数调用（Tool Calling）的主对话入口"""
        print(f"[LLM Client] 📡 正在请求模型: {cfg.LLM_MODEL} | 携带工具数: {len(tools) if tools else 0}")
        
        try:
            response = self.client.chat.completions.create(
                model=cfg.LLM_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else "none",
                temperature=temperature
            )
            return response.choices[0].message
        except Exception as e:
            print(f"[LLM Client] ❌ 请求失败: {e}")
            return None

# 单例导出
llm_service = LLMClient()