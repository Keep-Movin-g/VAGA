import hashlib
import json
from agent.llm_utils.omniparserclient import capture_screen, OmniParserClient
from config import cfg
import pygetwindow as gw
import time
class RuntimeContext:
    """运行时瞬时上下文，只存在于内存中"""
    def __init__(self):
        self.screenshot_obj = None
        self.screenshot_base64 = None
        self.som_base64 = None
        self.ui_elements = []
        self.current_clusters = []
        self.ui_tree_text = ""
        self.current_task = ""
        
        self.current_state_hash = None
        self.last_state_hash = None
        self.last_state_elements = []
        
        # ==========================================
        # 🌟 修复点 1：在这里把客户端初始化，整个生命周期只加载一次模型！
        # ==========================================
        print("[System] 正在初始化 OmniParser 视觉引擎 (仅执行一次)...")
        self.omni_client = OmniParserClient(cfg.OMNIPARSER_URL)

    def _calculate_state_hash(self, elements):
        """【计算画面指纹】过滤虚拟区，保证即使鼠标移动一点，只要界面核心没变 Hash 就不会变"""
        core_elements = [e for e in elements if not str(e.get('id', '')).startswith('9')]
        elements_str = json.dumps(core_elements, ensure_ascii=False, sort_keys=True)
        return f"state_{hashlib.md5(elements_str.encode('utf-8')).hexdigest()}"

    def refresh_vision(self, task_instruction: str):
        """刷新视觉：截图前隐藏 Web 窗口，截完后恢复"""
        print("\n[Context] 📸 正在捕获当前屏幕 (自动避让 Web 界面)...")
        
        target_title = "Agent OS 驾驶舱" # 必须与 app.py 中的 page_title 一致
        web_win = None
        
        try:
            # 1. 寻找 Streamlit 窗口
            wins = gw.getWindowsWithTitle(target_title)
            if wins:
                web_win = wins[0]
                # 2. 最小化窗口，防止被截进去
                web_win.minimize()
                # 给系统一点动画缓冲时间（Windows 动画大约 200-300ms）
                time.sleep(0.4) 
        except Exception as e:
            print(f"[Context] ⚠️ 尝试隐藏窗口失败: {e}")

        try:
            # 3. 执行核心截图与分析
            self.current_task = task_instruction
            # 这里调用你原来的截图逻辑
            self.screenshot_obj, self.screenshot_base64 = capture_screen()
            
            # 调用 OmniParser (保持你之前的单例模式)
            ui_data = self.omni_client.__call__(task_instruction=task_instruction)
            
            self.ui_elements = ui_data.get('parsed_content_list', [])
            self.som_base64 = ui_data.get("som_image_base64")
        
        finally:
            # 4. 无论截图成功与否，都要恢复 Web 窗口，否则你看不到网页了
            if web_win:
                try:
                    web_win.restore()
                    # 恢复后置顶，方便你继续观察
                    web_win.activate() 
                except:
                    pass

        print(f"[Context] ✅ 视觉刷新完成，已避开干扰。")