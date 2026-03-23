import os
import json
import uuid

class SessionManager:
    """基于 JSONL 的会话管理器，对齐 OpenClaw 的持久化策略"""
    def __init__(self, base_dir=".sessions"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_path(self, session_id: str) -> str:
        return os.path.join(self.base_dir, f"{session_id}.jsonl")

    def append(self, session_id: str, message: dict):
        """追加一条消息（O(1) 写入，防崩溃）"""
        path = self._get_path(session_id)
        # 为 tool_calls 转换对象格式以适应 JSON 序列化
        if "tool_calls" in message and message["tool_calls"]:
            msg_copy = message.copy()
            msg_copy["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} 
                if not isinstance(tc, dict) else tc 
                for tc in message["tool_calls"]
            ]
            message = msg_copy

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def load(self, session_id: str) -> list:
        """加载历史上下文"""
        path = self._get_path(session_id)
        if not os.path.exists(path):
            return []
        
        messages = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line.strip()))
        return messages