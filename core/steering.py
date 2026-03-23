import cv2
import numpy as np
import base64
import tkinter as tk
from tkinter import simpledialog
from PIL import Image, ImageDraw
from io import BytesIO
import keyboard

def check_human_steering(ctx, action_name: str, target_id: str = None, value: str = None) -> str:
    """
    触发右下角 HUD，并弹出带有数字 ID 和目标红圈的 OpenCV 预览图。
    放行(F8)返回 None，拒绝(Esc)则弹窗询问并返回纠错指令。
    """
    if action_name in ["wait", "finish", "None", None, "scroll_down", "scroll_up"]:
        return None

    print("\n[Steering] 👉 动作即将执行，请按 【F8】 放行 或 【Esc】 拒绝...")
    
    cv_img = None
    
    # =======================================================
    # 📸 1. 渲染带标记的预览图 (还原你原有的 CV2 逻辑)
    # =======================================================
    if ctx.som_base64:
        # 解码带数字 ID 的图像
        img = Image.open(BytesIO(base64.b64decode(ctx.som_base64)))
        draw = ImageDraw.Draw(img)
        
        # 如果有目标 ID，计算坐标并在图上画个显眼的红圈
        if target_id is not None:
            target_element = next((e for e in ctx.ui_elements if str(e.get('id', e.get('idx', ''))) == str(target_id)), None)
            if target_element and 'bbox' in target_element:
                bbox = target_element['bbox']
                sw, sh = img.size
                
                # 兼容绝对坐标与相对坐标 (0~1)
                x1 = bbox[0] * sw if bbox[0] <= 1.5 else bbox[0]
                y1 = bbox[1] * sh if bbox[1] <= 1.5 else bbox[1]
                x2 = bbox[2] * sw if bbox[2] <= 1.5 else bbox[2]
                y2 = bbox[3] * sh if bbox[3] <= 1.5 else bbox[3]
                
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                # 在目标位置画红圈
                draw.ellipse((cx-20, cy-20, cx+20, cy+20), outline='red', width=6)

        # 转换为 OpenCV 格式并显示
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        cv2.namedWindow("Agent_Preview", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Agent_Preview", 1400, 800) # 可根据你的屏幕适当调整
        cv2.imshow("Agent_Preview", cv_img)
        cv2.setWindowProperty("Agent_Preview", cv2.WND_PROP_TOPMOST, 1) # 置顶
        cv2.waitKey(1)

    # =======================================================
    # 🪟 2. 渲染右下角 HUD 悬浮窗
    # =======================================================
    hud = tk.Tk()
    hud.title("Agent 动作审查")
    w, h = 400, 200
    sw, sh = hud.winfo_screenwidth(), hud.winfo_screenheight()
    hud.geometry(f"{w}x{h}+{sw - w - 50}+80")
    hud.attributes("-topmost", True, "-alpha", 0.95, "-toolwindow", True)
    
    body = f"准备执行: {action_name}"
    if target_id: body += f" -> ID: {target_id}"
    if value: body += f" -> 输入/按键: {value}"
    
    tk.Label(hud, text="🧠 [Agent 决策]", font=("微软雅黑", 12, "bold"), fg="blue", anchor="w").pack(padx=15, pady=(15, 5), fill="x")
    tk.Label(hud, text=body, font=("微软雅黑", 11), anchor="w", wraplength=350).pack(padx=15, pady=5, fill="x")
    tk.Label(hud, text="👉 按【F8】放行，按【Esc】打断并纠错", font=("微软雅黑", 10, "bold"), fg="red").pack(padx=15, pady=15)
    hud.update()

    # =======================================================
    # ⌨️ 3. 监听键盘事件
    # =======================================================
    user_reject_reason = None
    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            if event.name == 'f8': 
                break 
            if event.name == 'esc':
                # 人类拒绝，销毁窗口
                hud.destroy()
                if cv_img is not None: cv2.destroyAllWindows()
                
                # 弹出纠错框
                root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
                reason = simpledialog.askstring("人工干预 (Steering)", "Agent 哪里做错了？请输入指导意见：", parent=root)
                root.destroy()
                user_reject_reason = reason if reason else "操作错误，请重新分析屏幕重新决策。"
                return user_reject_reason

    # 正常放行，销毁窗口
    hud.destroy()
    if cv_img is not None: cv2.destroyAllWindows()
    return None