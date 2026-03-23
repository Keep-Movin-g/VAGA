import json
import re
import base64
from openai import OpenAI
from config import cfg  # 🌟 统一配置源
from utils.prompt_loader import PromptLoader

class SomAnalyzer:
    def __init__(self):
        # 统一从中央配置获取，不再硬编码
        self.client = OpenAI(
            api_key=cfg.LLM_API_KEY,
            base_url=cfg.LLM_BASE_URL
        )
        self.loader = PromptLoader()

    # --- 🛠️ 内部工具封装 (Internal Helpers) ---

    def _prepare_image_url(self, base64_image) -> str:
        """【封装】Base64 净化：剥离换行、空格及各种前缀"""
        clean_b64 = str(base64_image).replace('\n', '').replace('\r', '').replace(' ', '').strip()
        
        # 处理可能的 bytes 字符串包裹逻辑
        if clean_b64.startswith(("b'", 'b"')):
            clean_b64 = clean_b64[2:-1]
            
        # 提取核心 base64 部分
        if "base64," in clean_b64:
            clean_b64 = clean_b64.split("base64,")[-1]
            
        return f"data:image/jpeg;base64,{clean_b64}"

    def _extract_json_from_text(self, text: str) -> str:
        """【封装】暴力提取 JSON：定位第一个 { 到最后一个 }"""
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return match.group(0)
        return text.strip()

    def _ask_vlm(self, prompt: str, img_url: str):
        """【封装】统一的大模型视觉请求入口"""
        response = self.client.chat.completions.create(
            model=cfg.LLM_MODEL, 
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
            top_p=0.9,
            extra_body={"enable_thinking": False}
        )
        return response.choices[0].message.content

    # --- 🧠 核心业务逻辑 ---

    def get_full_screen_semantics(self, som_base64_image):
        """让大模型一口气看完全图的所有 ID，并返回语义字典"""
        print("[SomAnalyzer] 🚀 启动全屏 SoM 狂暴流，正在让 VLM 批量识别所有 ID...")
        
        # 1. 准备数据
        prompt = self.loader.load("vlm_som_semantics.md")
        img_url = self._prepare_image_url(som_base64_image)

        # 2. 调遣 VLM (使用封装好的通信方法)
        raw_content = self._ask_vlm(prompt, img_url)
        
        # 3. 提取与解析 JSON
        clean_json_str = self._extract_json_from_text(raw_content)
        semantic_dict = json.loads(clean_json_str)
        
        print(f"[SomAnalyzer] ✅ 识别成功！VLM 一口气认出了 {len(semantic_dict)} 个元素的语义。")
        return semantic_dict

    def merge_semantics_to_elements(self, omni_elements, semantic_dict):
        """核心业务逻辑：将 OmniParser 的物理检测与 VLM 的语义逻辑『缝合』"""
        if not semantic_dict:
            print("[SomAnalyzer] ⚠️ 语义字典为空，跳过融合。")
            return omni_elements 

        merged_count = 0
        for item in omni_elements:
            # 兼容多种可能的 ID 键名
            idx = str(item.get('idx', item.get('id', item.get('ID', ''))))
            old_content = item.get('content', '') 
            
            if idx in semantic_dict:
                vlm_semantic = semantic_dict[idx]
                # 双剑合璧：Omni 负责文字，VLM 负责图标/意图
                item['content'] = f"[Omni识别: '{old_content}' | VLM识别: '{vlm_semantic}']"
                merged_count += 1
            else:
                item['content'] = f"[Omni识别: '{old_content}' | VLM未识别]"
                
        print(f"[SomAnalyzer] 🔗 结合完毕！共为 {merged_count} 个元素实现了双重语义识别。")
        return omni_elements
