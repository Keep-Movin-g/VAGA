import os
from dotenv import load_dotenv

# 加载 .env 里的内容
load_dotenv()

class Config:
    """全局配置类：集中管理所有外部参数"""
    
    # --- LLM 核心配置 ---
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus-2026-02-15")

    # --- 视觉感知配置 ---
    OMNIPARSER_URL = os.getenv("OMNIPARSER_URL", "http://localhost:8000/parse")

    # --- 决策参数 ---
    LAYOUT_THRESHOLD = float(os.getenv("LAYOUT_THRESHOLD", 0.85))
    SUBTASK_THRESHOLD = float(os.getenv("SUBTASK_THRESHOLD", 0.85))

    # --- 屏幕参数 (可以从此处统一缩放比例) ---
    SCREEN_WIDTH = 2560
    SCREEN_HEIGHT = 1600

# 实例化全局单例
cfg = Config()