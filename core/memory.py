import os
import json
import hashlib
import re
from utils.vector_memory import VectorGraphMemory

class UnifiedMemoryManager:
    """
    大一统记忆管理器：融合 GUI 图谱动作经验与文本语义经验。
    """
    def __init__(self, base_dir=".mini-agent/memory"):
        self.base_dir = base_dir
        self.index_path = os.path.join(self.base_dir, "text_index.json")
        self.text_entries = []
        self.loaded = False
        os.makedirs(self.base_dir, exist_ok=True)
        
        # 挂载你的图谱记忆引擎
        self.graph_db = VectorGraphMemory()

    def _load(self):
        if self.loaded: return
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    self.text_entries = json.load(f)
            except Exception:
                self.text_entries = []
        self.loaded = True

    def _save(self):
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.text_entries, f, ensure_ascii=False, indent=2)

    def _hash_content(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _extract_query_terms(self, query: str) -> list:
        tokens = re.findall(r'[a-zA-Z0-9\u4e00-\u9fa5]+', query.lower())
        return list(set(tokens))

    def _compute_keyword_score(self, content: str, query_terms: list) -> float:
        if not query_terms: return 0.0
        text = content.lower()
        doc_length = max(len(text), 1)

        matched_terms, total_tf = 0, 0.0
        for term in query_terms:
            tf = text.count(term)
            if tf > 0:
                matched_terms += 1
                total_tf += tf / (tf + 1.2)

        if matched_terms == 0: return 0.0
        coverage = matched_terms / len(query_terms)
        length_penalty = 1 - 0.75 + 0.75 * (doc_length / 500)
        return (coverage * total_tf) / length_penalty

    def add_text_memory(self, content: str, source: str = "memory") -> str:
        """保存纯文本经验"""
        self._load()
        content_hash = self._hash_content(content)
        entry_id = f"mem_{content_hash}"

        for entry in self.text_entries:
            if entry["hash"] == content_hash:
                entry["content"] = content
                self._save()
                return entry_id

        self.text_entries.append({
            "id": entry_id,
            "content": content,
            "source": source,
            "hash": content_hash,
        })
        self._save()
        return entry_id

    def add_graph_memory(self, from_hash, to_hash, from_elements, to_elements, action_data, subtask_label, status):
        """暴露给外层的图谱记忆写入接口"""
        self.graph_db.add_transition_edge(from_hash, to_hash, from_elements, to_elements, action_data, subtask_label, status)

    def search(self, query: str, current_ui_elements: list) -> str:
        """【究极融合搜索】同时检索图谱动作经验和文本经验"""
        self._load()
        result_text = f"🧠 针对任务 '{query}' 的记忆检索结果：\n\n"
        found_anything = False

        # 1. 检索图谱记忆 (GUI 动作经验)
        if current_ui_elements:
            graph_branch = self.graph_db.query_memory_branches(
                ui_elements=current_ui_elements,
                current_subtask=query,
                layout_threshold=0.85,
                subtask_threshold=0.85
            )
            
            if graph_branch:
                found_anything = True
                result_text += "【🎯 画面动作经验命中】\n"
                result_text += f"- 在极为相似的历史画面中，你曾成功执行过以下动作：\n"
                result_text += f"  * 动作类型: {graph_branch.get('action')}\n"
                result_text += f"  * 目标内容: {graph_branch.get('target_content')}\n"
                result_text += f"  * 输入值/快捷键: {graph_branch.get('action_value') or '无'}\n"
                result_text += "💡 (你可以直接参考此经验，调用 execute_gui_action 采取相同行动)\n\n"

        # 2. 检索文本记忆 (偏好与常识经验)
        query_terms = self._extract_query_terms(query)
        if query_terms:
            scored = []
            for entry in self.text_entries:
                score = self._compute_keyword_score(entry["content"], query_terms)
                if score > 0:
                    scored.append({"content": entry["content"], "score": score})
            
            if scored:
                found_anything = True
                scored.sort(key=lambda x: x["score"], reverse=True)
                result_text += "【📝 语义常识经验命中】\n"
                for i, res in enumerate(scored[:3]):
                    result_text += f"- {res['content'][:200]}\n"

        if not found_anything:
            return "记忆库中未找到与当前画面或任务相关的经验。请依靠视觉分析工具（如 analyze_ui_layout）进行探索。"
            
        return result_text