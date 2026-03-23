import os
import json
import sys
from datetime import datetime

class Logger:
    def __init__(self, base_dir="logs"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(base_dir, f"run_{timestamp}")

        if not os.path.exists(self.run_dir):
            os.makedirs(self.run_dir)

        self.log_file_path = os.path.join(self.run_dir, "execution.log")
        # 初始化时也调用对齐后的方法
        self.log_info(f"[System] Log directory created: {self.run_dir}")

    # 🌟 核心修复：增加 log_info 方法，对齐 Node 节点的调用接口
    def log_info(self, text):
        """记录普通信息"""
        self.log_text(f"[INFO] {text}")

    # 🌟 扩展：顺便增加 log_error，以后报错可以用
    def log_error(self, text):
        """记录错误信息"""
        self.log_text(f"[ERROR] {text}")

    def log_text(self, text):
        """底层的统一写入逻辑"""
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        message = f"{timestamp} {text}"

        # 1. 控制台打印 (带编码保护)
        try:
            print(message)
        except UnicodeEncodeError:
            print(message.encode('ascii', 'ignore').decode('ascii'))

        # 2. 写入文件
        with open(self.log_file_path, "a", encoding="utf-8") as f:
            f.write(message + "\n")

    def save_step(self, step_num, screenshot, ui_elements, plan):
        """保存步骤快照：截图、元素和决策 JSON"""
        # 保存截图
        img_path = os.path.join(self.run_dir, f"step_{step_num}_vision.png")
        screenshot.save(img_path)

        # 保存 UI 元素 (保持你原来的简化逻辑)
        elements_simple = [
            {"id": i, "content": e.get('content', '')[:100], "bbox": e.get('bbox')}
            for i, e in enumerate(ui_elements)
        ]
        with open(os.path.join(self.run_dir, f"step_{step_num}_elements.json"), "w", encoding="utf-8") as f:
            json.dump(elements_simple, f, ensure_ascii=False, indent=2)

        # 保存大脑决策
        with open(os.path.join(self.run_dir, f"step_{step_num}_plan.json"), "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)