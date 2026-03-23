import pyautogui
import time
import pyperclip
import ctypes
import os
import pygetwindow as gw
class Hand:
    def __init__(self):
        # PyAutoGUI 安全设置
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.3  # 稍微加快动作响应
        
        # 配置参数
        self.SCREEN_SCALE = 1.0  # 如果有 DPI 缩放问题可以在此调整
        self.SCROLL_AMOUNT = 800  # 默认滚动力度
    def _hide_web_console(self):
        """隐藏控制台窗口并返回窗口对象以便后续恢复"""
        try:
            wins = gw.getWindowsWithTitle(self.web_title)
            if wins:
                win = wins[0]
                if not win.isMinimized:
                    win.minimize()
                    time.sleep(0.4) # 等待窗口收起的动画
                return win
        except Exception as e:
            print(f"[Hand] ⚠️ 隐藏窗口失败: {e}")
        return None
    # ==================== 🛠️ 系统辅助工具 ====================

    def _ensure_english_input(self):
        """强制切换输入法为英文，防止 type 模式下出中文"""
        try:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            hwnd = user32.GetForegroundWindow()
            # WM_INPUTLANGCHANGEREQUEST: 0x0050, US-English: 0x04090409
            user32.PostMessageW(hwnd, 0x0050, 0, 0x04090409)
            time.sleep(0.1)
        except Exception as e:
            print(f"[Hand] ⚠️ 输入法切换警告: {e}")

    # ==================== 🎯 坐标换算核心 ====================

    def get_coordinates(self, target_id, ui_elements, img_size):
        """将 OmniParser 的 ID 换算成屏幕真实像素坐标"""
        if target_id is None: return None
        
        element = next((e for e in ui_elements if str(e.get('id', '')) == str(target_id)), None)
        if not element or 'bbox' not in element:
            print(f"[Hand] ❌ 找不到 ID 为 {target_id} 的视觉元素")
            return None

        bbox = element['bbox']
        # 计算中心点比例
        raw_cx, raw_cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        
        # 换算为像素 (兼容 0-1 比例和原始像素值)
        sw, sh = img_size
        cx = raw_cx * sw if raw_cx <= 1.5 else raw_cx
        cy = raw_cy * sh if raw_cy <= 1.5 else raw_cy

        # 边缘保护：防止触发 PyAutoGUI 的 0,0 坐标熔断
        return (max(int(cx), 5), max(int(cy), 5))

    # ==================== 🚀 动作路由 (入口) ====================

    def execute(self, action, target_coords=None, value=None, input_mode="paste"):
        """
        修正版：严格确保先隐藏，再操作
        """
        # 1. 立即定义物理动作白名单
        physical_actions = ["left_click", "double_click", "right_click", "type", "type_and_enter", "scroll_down", "scroll_up", "hotkey"]
        
        web_win = None
        
        # 🌟 关键修正：在任何 Print 或逻辑分发之前，先执行隐藏
        if action in physical_actions:
            # 找到窗口
            web_win = self._find_web_window()
            if web_win and not web_win.isMinimized:
                # 打印日志（此时窗口还没动）
                print(f"[Hand] 🛡️ 物理动作安全防护：正在避让控制台...")
                web_win.minimize()
                # 🔴 重要：必须等待，否则最小化还没完成，鼠标就点下去了
                time.sleep(1.0) 

        try:
            # 2. 现在才开始处理逻辑动作
            if action == "finish":
                return False
            
            if action in ["scroll_down", "scroll_up", "wait"]:
                return self._execute_global(action)

            # 3. 执行物理点击/输入
            # 此时 Web 窗口已确定最小化，桌面是干净的
            if "click" in action:
                self._do_click(target_coords, action)
            elif "type" in action:
                self._do_type(target_coords, value, input_mode, press_enter=("enter" in action))
            
            # 动作执行完，多等 0.2s 确保系统响应了点击
            time.sleep(0.2)

        finally:
            # 4. 最后恢复窗口
            if web_win:
                web_win.restore()
                # web_win.activate() # 可选：重新夺回焦点
        
        return True

    def _find_web_window(self):
        """抽离出的窗口查找逻辑"""
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle("Agent OS 驾驶舱")
            return wins[0] if wins else None
        except:
            return None

    # ==================== 🖱️ 底层原子动作 ====================

    def _execute_global(self, action):
        """执行滚动与等待"""
        if action == "scroll_down":
            print(f"[Hand] ⏬ 向下滚动 {self.SCROLL_AMOUNT}")
            pyautogui.scroll(-self.SCROLL_AMOUNT)
        elif action == "scroll_up":
            print(f"[Hand] ⏫ 向上滚动 {self.SCROLL_AMOUNT}")
            pyautogui.scroll(self.SCROLL_AMOUNT)
        elif action == "wait":
            print("[Hand] ⏳ 等待页面响应...")
            time.sleep(2)
        
        time.sleep(1) # 滚动后的惯性等待
        return True

    def _execute_hotkey(self, keys_string, coords=None):
        """执行快捷键，可选先点击聚焦"""
        if coords:
            pyautogui.click(coords[0], coords[1])
            time.sleep(0.3)
            
        keys = [k.strip().lower() for k in keys_string.replace(',', '+').split('+')]
        keys = ['win' if k in ['windows', 'command'] else k for k in keys]
        
        print(f"[Hand] 🎹 组合键: {' + '.join(keys)}")
        pyautogui.hotkey(*keys)
        time.sleep(0.8)
        return True

    def _do_click(self, coords, click_type):
        """执行各类点击"""
        x, y = coords
        pyautogui.moveTo(x, y, duration=0.4) # 模拟真人平滑移动
        
        if click_type == "double_click":
            pyautogui.doubleClick()
            time.sleep(2) # 双击通常意味着打开程序，多等会儿
        elif click_type == "right_click":
            pyautogui.rightClick()
        else:
            pyautogui.click()
        time.sleep(0.5)

    def _do_type(self, coords, text, mode, press_enter=False):
        """执行文本输入"""
        if not text: return
        
        # 1. 激活并清空输入框
        pyautogui.click(coords[0], coords[1])
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        time.sleep(0.2)

        # 2. 输入内容
        if mode == "paste":
            print(f"[Hand] 📋 粘贴输入: {text}")
            pyperclip.copy(str(text))
            pyautogui.hotkey('ctrl', 'v')
        else:
            self._ensure_english_input()
            print(f"[Hand] ⌨️ 硬件模拟输入: {text}")
            pyautogui.write(str(text), interval=0.02)

        # 3. 回车确认
        if press_enter:
            time.sleep(0.3)
            pyautogui.press('enter')