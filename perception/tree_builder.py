import json
import re
from openai import OpenAI
from config import cfg  # 🌟 引入中央配置
from utils.prompt_loader import PromptLoader

class TreeBuilder:
    def __init__(self):
        # 1. 统一从 config 取配置
        self.client = OpenAI(
            api_key=cfg.LLM_API_KEY,
            base_url=cfg.LLM_BASE_URL
        )
        self.loader = PromptLoader()

    # --- 🛠️ 内部私有工具函数 (Internal Helpers) ---

    def _prepare_image_url(self, base64_image) -> str:
        """【封装】终极 Base64 净化与格式化逻辑"""
        clean_b64 = str(base64_image).replace('\n', '').replace('\r', '').replace(' ', '').strip()
        
        # 处理可能的 bytes 字符串包裹
        if clean_b64.startswith(("b'", 'b"')):
            clean_b64 = clean_b64[2:-1]
            
        # 剥离前缀
        if "base64," in clean_b64:
            clean_b64 = clean_b64.split("base64,")[-1]
            
        return f"data:image/jpeg;base64,{clean_b64}"

    def _clean_json(self, text: str) -> str:
        """【封装】确保提取出纯净的 JSON 块"""
        # 暴力提取第一个 { 到最后一个 } 之间的内容
        match = re.search(r'\{.*\}|\[.*\]', text, re.DOTALL)
        if match:
            return match.group(0)
        return text.strip()

    def _ask_vlm(self, prompt: str, img_url: str, model="qwen3.5-plus"):
        """【封装】统一的大模型请求入口"""
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": img_url}}
                    ]
                }
            ],
            temperature=0.1,
            extra_body={"enable_thinking": False}
        )
        return response.choices[0].message.content

    # --- 🧠 核心业务方法 ---



    def get_clustered_semantics(self, som_base64_image, current_task):
        """3. UI 组件视觉语义聚类"""
        print("[TreeBuilder] 🚀 启动 VLM 视觉语义聚类...")
        
        prompt = self.loader.load("vlm_clustering.md").replace("{user_task}", current_task)
        img_url = self._prepare_image_url(som_base64_image)

        raw_content = self._ask_vlm(prompt, img_url)
        
        print(f"\n[Debug] 大模型原始返回:\n{raw_content}")
        clean_json_str = self._clean_json(raw_content)
        clusters = json.loads(clean_json_str)
        
        print(f"\n[Debug - TreeBuilder] 📦 VLM 成功解析出 {len(clusters)} 个组件簇。预览：")
        for idx, c in enumerate(clusters[:3]): # 仅打印前3个
            print(f"  - 簇 {idx+1}: [{c.get('component_name')}] -> 核心 ID: {c.get('primary_click_id')}")
        
        return clusters