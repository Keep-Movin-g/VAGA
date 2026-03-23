import requests
import base64
from pathlib import Path
import os
import uuid
import numpy as np
import pyautogui
from paddleocr import PaddleOCR
from sentence_transformers import SentenceTransformer, util
from agent.llm_utils.utils import encode_image

OUTPUT_DIR = "./tmp/outputs"

def capture_screen():
    screenshot = pyautogui.screenshot()
    if screenshot.mode != 'RGB':
        screenshot = screenshot.convert('RGB')

    screenshot_uuid = uuid.uuid4()
    filename = f"screenshot_{screenshot_uuid}.png"
    screenshot_path = os.path.join(OUTPUT_DIR, filename)
    screenshot.save(screenshot_path)
    return screenshot, str(screenshot_path)

class OmniParserClient:
    def __init__(self, url: str) -> None:
        self.url = url
        
        # 1. 初始化 OCR (用于修正坐标内的文字)
        # use_angle_cls=True 可以提高检测率，show_log=False 关闭刷屏日志
        self.ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        
        # 2. 初始化语义模型 (换用多语言版本，支持中文理解)
        print("[System] Loading Multilingual embedding model...")
        # 这个模型约 400MB，第一次运行会自动下载
        self.embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        print("[System] Model loaded.")

    def _contains_chinese(self, text):
        """判断字符串是否包含中文字符"""
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return True
        return False

    def __call__(self, task_instruction: str = None):
        """
        核心调用入口
        task_instruction: 用户的当前任务指令，用于语义过滤
        """
        # 1. 截图
        screenshot, screenshot_path = capture_screen()
        image_base64 = encode_image(screenshot_path)
        
        # 2. 请求 OmniParser 服务
        try:
            response = requests.post(self.url, json={"base64_image": image_base64}, timeout=30)
            response.raise_for_status()
            response_json = response.json()
        except Exception as e:
            print(f"[Error] OmniParser API failed: {e}")
            return None

        # 3. 保存标记图 (调试用)
        if 'som_image_base64' in response_json:
            som_image_data = base64.b64decode(response_json['som_image_base64'])
            screenshot_path_uuid = Path(screenshot_path).stem.replace("screenshot_", "")
            som_screenshot_path = f"{OUTPUT_DIR}/screenshot_som_{screenshot_path_uuid}.png"
            with open(som_screenshot_path, "wb") as f:
                f.write(som_image_data)
        else:
            screenshot_path_uuid = "unknown"
        
        # 4. PaddleOCR 修正 (可选，增强 OCR 精度)
        try:
            img_np = np.array(screenshot)
            ocr_raw = self.ocr.ocr(img_np, cls=True)
            ocr_data = []
            if ocr_raw:
                # 处理不同版本的 PaddleOCR 返回格式差异
                if isinstance(ocr_raw[0], list) and len(ocr_raw[0]) == 2 and isinstance(ocr_raw[0][0], list):
                    ocr_data = ocr_raw
                elif isinstance(ocr_raw[0], list):
                    ocr_data = ocr_raw[0]
            
            if ocr_data:
                h, w = screenshot.size[1], screenshot.size[0]
                for element in response_json.get("parsed_content_list", []):
                    # 只修正 Text 类型，Icon 类型通常不需要修正
                    if element['type'] == 'text':
                        bbox = element['bbox']
                        ymin, xmin, ymax, xmax = bbox[0]*h, bbox[1]*w, bbox[2]*h, bbox[3]*w
                        for line in ocr_data:
                            if not line or len(line) < 2: continue
                            ocr_box = line[0]
                            ocr_text = line[1][0]
                            # 计算中心点重合度
                            ocx = (ocr_box[0][0] + ocr_box[2][0]) / 2
                            ocy = (ocr_box[0][1] + ocr_box[2][1]) / 2
                            if xmin <= ocx <= xmax and ymin <= ocy <= ymax:
                                element['content'] = ocr_text
                                break
        except Exception as e:
            print(f"[Warning] OCR refinement warning: {e}")

        # 5. 补充参数
        response_json['width'] = screenshot.size[0]
        response_json['height'] = screenshot.size[1]
        response_json['original_screenshot_base64'] = image_base64
        response_json['screenshot_uuid'] = screenshot_path_uuid
        if 'latency' not in response_json:
            response_json['latency'] = 0.0 
            
        # 6. 【关键】调用过滤与格式化逻辑
        response_json = self.reformat_messages(response_json, current_task=task_instruction)
        return response_json
    
    def reformat_messages(self, response_json: dict, current_task: str = ""):
        """
        过滤逻辑：
        1. 英文/符号 -> VIP保留
        2. 短中文文本 -> 视为按钮保留
        3. 其他中文 (图标/长文) -> 语义过滤
        
        展示逻辑：
        直接展示所有保留下来的元素内容 (Icon 和 Text 都明文展示)。
        """
        screen_info = ""
        elements = response_json.get("parsed_content_list", [])
        if not elements:
            response_json['screen_info'] = "No elements detected."
            return response_json

        kept_elements = []
        candidates_for_filtering = []    
        candidates_indices = []          
        
        # 阈值：中文按钮通常小于等于6个字 (如"立即购买","搜索")
        CHINESE_BUTTON_THRESHOLD = 6
        
        print(f"\n[Debug Filter] Current Task: '{current_task}'")
        
        # === 阶段一：初筛 ===
        for e in elements:
            content = e.get('content', '').strip()
            e_type = e.get('type', 'text') # icon or text
            idx = e.get('idx', elements.index(e))

            # 1. 空内容：保留 (纯图形Icon)
            if not content:
                kept_elements.append(e)
                continue

            # 2. 非中文 (英文/数字/符号) -> VIP 通道
            if not self._contains_chinese(content):
                # 过滤掉极长的代码块或报错信息
                if len(content) < 50:
                    kept_elements.append(e)
                else:
                    print(f"[Debug] ID {idx} Removed (English content too long)")
                continue
            
            # 3. 中文内容 -> 严查
            if self._contains_chinese(content):
                # 3.1 纯文本且很短 -> 视为按钮，保留
                # 注意：如果是 Icon 类型且含中文，不管多短都扔去审核 (防止把"垃圾桶"图标当成文字)
                if e_type == 'text' and len(content) <= CHINESE_BUTTON_THRESHOLD:
                    kept_elements.append(e)
                    continue
                
                # 3.2 其他中文 -> 待审列表
                candidates_for_filtering.append(content)
                candidates_indices.append(e)

        # === 阶段二：语义过滤 ===
        if candidates_for_filtering and current_task:
            try:
                # 截取任务前30个字，避免无关描述稀释语义
                short_task = current_task[:30]
                
                task_emb = self.embedding_model.encode(short_task, convert_to_tensor=True)
                content_embs = self.embedding_model.encode(candidates_for_filtering, convert_to_tensor=True)
                
                cosine_scores = util.cos_sim(task_emb, content_embs)[0]
                
                for score, element in zip(cosine_scores, candidates_indices):
                    idx = element.get('idx', 'unk')
                    content_preview = element.get('content', '')[:10]
                    
                    # 阈值 0.25 (配合多语言模型，区分度更好)
                    if score > 0.25: 
                        kept_elements.append(element)
                        print(f"[Debug] ID {idx} Kept (Score {score:.2f} > 0.25): {content_preview}...")
                    else:
                        print(f"[Debug] ID {idx} REMOVED (Score {score:.2f} <= 0.25): {content_preview}...")
                        
            except Exception as e:
                print(f"[Warning] Semantic filter error: {e}, keeping all candidates as fallback.")
                kept_elements.extend(candidates_indices)
        else:
            # 如果没传任务，或者任务为空，只能保留所有（防止误删）
            if candidates_indices:
                print(f"[Debug] ⚠️ Fallback triggered: Task is empty or None. Keeping {len(candidates_indices)} Chinese items.")
                kept_elements.extend(candidates_indices)

        # === 阶段三：组装展示内容 ===
        # 恢复原始顺序
        kept_elements.sort(key=lambda x: elements.index(x))

        for element in kept_elements:
            idx = element.get('idx', elements.index(element))
            content = element.get("content", "")
            
            # 将 text 转为 Text，icon 转为 Icon，让 Prompt 输出更规范
            e_type_formatted = element.get('type', 'text').capitalize()
            
            # 直接明文展示内容，取消隐藏逻辑
            screen_info += f'ID: {idx}, {e_type_formatted}: {content}\n'
        
        response_json['screen_info'] = screen_info
        print(f"[Final] Kept {len(kept_elements)}/{len(elements)} items.\n")
        return response_json