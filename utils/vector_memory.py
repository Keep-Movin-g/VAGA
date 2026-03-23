import os
import re
import json
import networkx as nx
import difflib
from config import cfg

class VectorGraphMemory:
    def __init__(self):
        self.db_path = cfg.MEMORY_GRAPH_PATH if hasattr(cfg, 'MEMORY_GRAPH_PATH') else "skills/agent_vector_brain.graphml"
        print("[VectorGraphMemory] 🧠 初始化子任务级马尔可夫图谱...")
        self.graph = self._load_graph()

    # --- 🛠️ 1. 底层工具封装 (Internal Helpers) ---

    def _load_graph(self) -> nx.DiGraph:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        if os.path.exists(self.db_path):
            g = nx.read_graphml(self.db_path)
            print(f"[VectorGraphMemory] 🕸️ 唤醒数据库: {g.number_of_nodes()} 节点, {g.number_of_edges()} 连线")
            return g
        return nx.DiGraph()

    def _save_graph(self):
        temp_path = self.db_path + ".tmp"
        nx.write_graphml(self.graph, temp_path)
        os.replace(temp_path, self.db_path)

    def _filter_core_elements(self, elements_data):
        if not elements_data: return []
        if isinstance(elements_data, str):
            elements_data = json.loads(elements_data)
        return [e for e in elements_data if e.get('type') != 'Inverted_Blank_Zone']

    def _calculate_subtask_similarity(self, sub1, sub2):
        """【封装】计算两个子任务描述的文本相似度"""
        if not sub1 or not sub2: return 0.0
        return difflib.SequenceMatcher(None, sub1.lower(), sub2.lower()).ratio()

    def _calculate_iou(self, boxA, boxB):
        if not boxA or not boxB or len(boxA) != 4 or len(boxB) != 4: return 0.0
        xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
        xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
        interArea = max(0, xB - xA) * max(0, yB - yA)
        if interArea == 0: return 0.0
        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        return interArea / float(boxAArea + boxBArea - interArea)

    def _calculate_layout_similarity(self, current_elements, memory_elements):
        if not current_elements or not memory_elements: return 0.0
        match_score = 0.0
        for curr_item in current_elements:
            best_item_score = 0.0
            curr_text = str(curr_item.get('text', curr_item.get('content', ''))).strip().lower()
            curr_bbox = curr_item.get('bbox')
            for mem_item in memory_elements:
                mem_text = str(mem_item.get('text', mem_item.get('content', ''))).strip().lower()
                mem_bbox = mem_item.get('bbox')
                text_sim = 1.0 if curr_text and curr_text == mem_text else (0.5 if (curr_text in mem_text or mem_text in curr_text) else 0.0)
                iou = self._calculate_iou(curr_bbox, mem_bbox)
                score = (text_sim * 0.2) + (iou * 0.8)
                if score > best_item_score: best_item_score = score
            match_score += best_item_score
        return match_score / len(current_elements)

    # --- 🧠 2. 核心业务方法 ---

    def query_memory_branches(self, ui_elements, current_subtask, layout_threshold=0.8, subtask_threshold=0.8):
        """
        【查询层】两步匹配：1. 找布局最像的节点；2. 在该节点的出边找子任务名最像的动作。
        """
        if self.graph.number_of_nodes() == 0: return None
        
        current_core = self._filter_core_elements(ui_elements)
        if not current_core: return None
        
        best_node, highest_layout_sim = None, 0.0

        # 第一步：空间布局匹配
        for u, data in self.graph.nodes(data=True):
            memory_core = self._filter_core_elements(data.get('omni_elements', '[]'))
            if not memory_core: continue
            
            l_sim = self._calculate_layout_similarity(current_core, memory_core)
            if l_sim > highest_layout_sim:
                highest_layout_sim = l_sim
                best_node = u

        if highest_layout_sim < layout_threshold or not best_node:
            print(f"[VectorMemory] 📉 布局不匹配 (最高: {highest_layout_sim:.2f})")
            return None

        # 第二步：子任务语义匹配
        print(f"[VectorMemory] 🎯 布局命中！正在匹配子任务: '{current_subtask}' 分数: {highest_layout_sim:.2f}")
        best_edge_data = None
        highest_sub_sim = 0.0

        for _, _, edge_data in self.graph.out_edges(best_node, data=True):
            stored_subtask = edge_data.get('subtask_label', '')
            s_sim = self._calculate_subtask_similarity(current_subtask, stored_subtask)
            
            if s_sim > highest_sub_sim:
                highest_sub_sim = s_sim
                best_edge_data = edge_data

        if highest_sub_sim >= subtask_threshold:
            print(f"[VectorMemory] ✅ 命中经验！子任务匹配度: {highest_sub_sim:.2f}")
            return best_edge_data
        else:
            print(f"[VectorMemory] 📉 子任务不匹配 (最高: {highest_sub_sim:.2f}),  best_edge_data: {best_edge_data},current_subtask: {current_subtask}")
            
        return None

    def add_transition_edge(self, from_hash, to_hash, from_elements, to_elements, action_data, subtask_label, status):
        """
        【学习层】只有当 status == 1 (执行成功) 时才保存。
        保存 subtask_label (子任务名)，不再保存模糊的总任务名。
        """
        if status != 1:
            print(f"[Memory] ⏭️ 子任务 '{subtask_label}' 状态为失败/未完成，跳过存盘。")
            return

        print(f"[Memory] 🌌 记录成功路径: {from_hash} --[{subtask_label}]--> {to_hash}")
        
        # 确保节点存在
        for h, elems in [(from_hash, from_elements), (to_hash, to_elements)]:
            if not self.graph.has_node(h):
                clean_str = json.dumps(self._filter_core_elements(elems), ensure_ascii=False)
                self.graph.add_node(h, omni_elements=clean_str)

        # 建立连线，存储子任务标签
        def _c(v): return v if v is not None else ""
        self.graph.add_edge(
            from_hash, to_hash,
            subtask_label=subtask_label, # 🌟 核心：存储子任务名字
            action=_c(action_data.get('next_action')),
            rel_x=action_data.get('rel_x', 0.0),
            rel_y=action_data.get('rel_y', 0.0),
            action_value=_c(action_data.get('action_value')),
            input_mode=_c(action_data.get('input_mode')),
            target_content=_c(action_data.get('target_content'))
        )
        
        self._save_graph()