import uiautomation as auto
import json

class FusionEngine:
    def __init__(self, screen_w=1920, screen_h=1080):
        self.screen_w = screen_w
        self.screen_h = screen_h

    # ==========================================
    # 🛠️ 第一部分：基础工具封装 (Helpers)
    # ==========================================

    def _normalize_coords(self, bbox):
        """【封装】处理不同格式的 bbox，返回统一的 (cx, cy) 绝对坐标"""
        if not bbox or len(bbox) != 4:
            return None, None
            
        # 兼容处理：OmniParser 偶尔会返回 [x, y, w, h] 而不是 [x1, y1, x2, y2]
        if 2.0 < bbox[2] < self.screen_w / 2: 
            cx, cy = bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2
        else:
            cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
            
        # 强制转换为绝对像素坐标 (如果输入是 0~1 的相对坐标)
        abs_x = cx * self.screen_w if cx <= 1.5 else cx
        abs_y = cy * self.screen_h if cy <= 1.5 else cy
        return abs_x, abs_y

    def _get_element_id(self, item):
        """【封装】统一获取各种可能的 ID 键名"""
        return str(item.get('idx', item.get('id', item.get('ID', ''))))

    def _find_best_uia_node(self, abs_x, abs_y, uia_nodes):
        """【封装】在 UIA 节点池中进行“命中测试”，找面积最小（最精准）的节点"""
        hit_nodes = []
        for node in uia_nodes:
            r = node["rect"]
            if r.left <= abs_x <= r.right and r.top <= abs_y <= r.bottom:
                hit_nodes.append(node)
        
        if not hit_nodes:
            return None
        return min(hit_nodes, key=lambda x: x["area"])

    # ==========================================
    # 🔍 第二部分：数据获取封装
    # ==========================================

    def _get_os_uia_nodes(self):
        """【封装】获取 Windows 原生 UI 树节点"""
        uia_nodes = []
        fg_window = auto.GetForegroundControl()
        if not fg_window: return uia_nodes
        
        for control, _ in auto.WalkControl(fg_window, maxDepth=5):
            rect = control.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                uia_nodes.append({
                    "name": control.Name,
                    "type": control.ControlTypeName,
                    "rect": rect,
                    "area": rect.width() * rect.height()
                })
        return uia_nodes

    # ==========================================
    # 🌿 第三部分：空白区域邻域探测 (新增)
    # ==========================================

    def _is_left_clear(self, x, y, omni_elements, gap=150, y_tolerance=10):
        """检查目标点 (x, y) 左侧的 gap 像素内是否有其他实体碰撞"""
        for el in omni_elements:
            curr_id = str(el.get('id', el.get('idx', '')))
            if curr_id.startswith('9'):  # 忽略虚拟节点和全屏底板
                continue
                
            bbox = el.get('bbox')
            if not bbox or len(bbox) != 4: continue
            
            x1, y1, x2, y2 = [
                v * (self.screen_w if i % 2 == 0 else self.screen_h) if v <= 1.5 else v 
                for i, v in enumerate(bbox)
            ]
            
            # 🌟 核心逻辑：定义一个左侧检测框
            # 左边界为 x-gap，右边界为 x；上下边界为 y ± y_tolerance
            # 只要实体元素的包围盒跟这个“左侧通道”有交集，就说明左侧不清净
            if (x1 < x) and (x2 > x - gap) and (y1 < y + y_tolerance) and (y2 > y - y_tolerance):
                return False
        return True

    
    # ==========================================
    # 🧠 第四部分：核心融合业务 (原始保留)
    # ==========================================

    def inject_blank_zones(self, omni_elements, clusters):
        """为现有元素生成“右侧空白”虚拟节点 (左侧 150 像素安全净空版)"""
        augmented_elements = list(omni_elements)
        blank_id_start = 901
        
        if not clusters:
            return augmented_elements

        omni_dict = {str(el.get('id', el.get('idx', ''))): el for el in omni_elements}
        max_blanks_per_cluster = 1 

        for cluster in clusters:
            target_ids = []
            if cluster.get('primary_click_id'):
                target_ids.append(str(cluster.get('primary_click_id')))
            for tid in cluster.get('included_ids', []):
                if str(tid) not in target_ids:
                    target_ids.append(str(tid))
            
            blanks_in_this_cluster = 0
            cluster_name = cluster.get('component_name', '未知组件')
            
            # 🌟 新增：为当前组件生成一个唯一标识符，方便后续认领孩子
            cluster_uuid = f"{cluster_name}_{cluster.get('primary_click_id', 'none')}"
            
            for tid in target_ids:
                if blanks_in_this_cluster >= max_blanks_per_cluster:
                    break 
                    
                el = omni_dict.get(tid)
                if not el: continue
                
                if el.get('type') == 'Virtual_Blank' or str(el.get('id', '')).startswith('9'):
                    continue
                    
                bbox = el.get('bbox')
                if not bbox or len(bbox) != 4: continue

                x2 = bbox[2] * self.screen_w if bbox[2] <= 1.5 else bbox[2]
                y_mid = (bbox[1] + bbox[3]) / 2
                y_mid = y_mid * self.screen_h if y_mid <= 1.5 else y_mid
                
                for step in range(1, 25):
                    distance = 100 + step * 50  
                    probe_x = x2 + distance
                    
                    if probe_x >= self.screen_w - 150:
                        break 
                        
                    # 🌟 核心修改：改为调用 _is_left_clear
                    if self._is_left_clear(probe_x, y_mid, omni_elements, gap=150):
                        raw_content = str(el.get('content', el.get('text', '未知元素')))
                        clean_name = raw_content
                        if "Omni识别:" in raw_content:
                            try:
                                clean_name = raw_content.split("Omni识别:")[1].split("|")[0].strip(" '[]")
                            except Exception:
                                clean_name = raw_content[:15]
                        
                        augmented_elements.append({
                            "id": blank_id_start,
                            "idx": blank_id_start,
                            "type": "Virtual_Blank",
                            "parent_uuid": cluster_uuid,  # 🌟 核心修改：绑定所属的组件 ID
                            "content": f"位于组件 [{cluster_name}] 中 ID {tid} ({clean_name[:8]}) 右侧 {distance} 像素 (左侧净空>150px)",
                            "bbox": [probe_x - 5, y_mid - 5, probe_x + 5, y_mid + 5]
                        })
                        blank_id_start += 1
                        blanks_in_this_cluster += 1
                        break 
                        
        return augmented_elements

    def fuse_clustered_data(self, omni_elements, clusters):
        """【聚类融合】将 Omni 散件打包，并将虚拟空白节点归入对应组件"""
        if not clusters: return "聚类失败，降级展示原始数据。"

        omni_dict = {self._get_element_id(el): el.get('content', '') for el in omni_elements}
        final_text = "【逻辑组件列表】\n"
        
        component_idx = 1

        for cluster in clusters:
            comp_name = cluster.get('component_name', '未知组件')
            inc_ids = [str(x) for x in cluster.get('included_ids', [])]
            
            if "空白" in comp_name and len(inc_ids) > 0:
                if "搜索" in comp_name:
                    comp_name = comp_name.replace("空白", "输入") 
                else:
                    comp_name = comp_name.replace("空白", "实体")

            # 1. 提取该组件原有的真实节点 OCR
            omni_texts = [f"[ID {tid}: '{omni_dict[tid]}']" for tid in inc_ids if tid in omni_dict and omni_dict[tid].strip()]
            
            # 🌟 2. 核心修改：寻找属于该组件的虚拟空白节点，并追加到尾部
            cluster_uuid = f"{comp_name}_{cluster.get('primary_click_id', 'none')}"
            for el in omni_elements:
                if el.get('type') == 'Virtual_Blank' and el.get('parent_uuid') == cluster_uuid:
                    # 按照你的格式要求组装
                    omni_texts.append(f"[ID {el.get('id')}]: {el.get('content')}")
            
            # 3. 组装最终文本
            final_text += f"🔹 组件 [{component_idx}]: {comp_name}\n"
            final_text += f"   - 交互 ID: {cluster.get('primary_click_id')}\n"
            final_text += f"   - 精准 OCR: {' | '.join(omni_texts) or '无'}\n\n"
            component_idx += 1

        return final_text.strip()