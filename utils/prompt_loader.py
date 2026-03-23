import os

import os

class PromptLoader:
    # 🌟 修改点 1：把默认的目标文件夹改为 'prompts'
    def __init__(self, target_dir="prompts"):
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # 🌟 修改点 2：变量名从 skills_dir 改为更通用的 target_dir
        self.target_dir = os.path.join(base_path, target_dir)

    def load(self, filename: str) -> str:
        file_path = os.path.join(self.target_dir, filename)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"[Error] 找不到目标文件: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()