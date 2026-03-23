import os
import re
import json
from perception.Verify_Action import SomAnalyzer
from perception.tree_builder import TreeBuilder
from perception.fusion import FusionEngine
from utils.hand import Hand
from core.memory import UnifiedMemoryManager
from utils.prompt_loader import PromptLoader

class SkillManager:
    """动态技能注册与分发中心 (Agent 的工具箱)"""
    def __init__(self, context):
        self.ctx = context
        self.memory = UnifiedMemoryManager()
        
        # 懒加载底层组件，防止启动时过度消耗资源
        self._som = None
        self._tree = None
        self._hand = None
        
        # 动态技能注册表
        self._skills = {}
        self._register_builtin_skills()

    # --- 底层组件懒加载 ---
    def get_som(self):
        if not self._som: self._som = SomAnalyzer()
        return self._som
        
    def get_tree(self):
        if not self._tree: self._tree = TreeBuilder()
        return self._tree
        
    def get_hand(self):
        if not self._hand: self._hand = Hand()
        return self._hand

    # --- 技能编排与调度机制 ---
    def register_skill(self, name: str, schema: dict, handler_func):
        self._skills[name] = {"schema": schema, "handler": handler_func}

    def execute(self, tool_name: str, arguments_str: str) -> str:
        if tool_name not in self._skills: return f"❌ 未知工具: {tool_name}"
        try:
            args = json.loads(arguments_str) if arguments_str else {}
            return self._skills[tool_name]["handler"](args)
        except Exception as e:
            return f"❌ 工具执行异常: {str(e)}"

    def get_schemas(self):
        return [{"type": "function", "function": skill["schema"]} for skill in self._skills.values()]

    # ==========================================================
    # 🛠️ 注册内置工具 (Tool/MCP)
    # ==========================================================
    def _register_builtin_skills(self):
        
        # 1. 语义识别
        self.register_skill(
            name="recognize_semantics",
            schema={
                "name": "recognize_semantics",
                "description": "【强制要求】当你要点击一个没有文字的纯图标，或者屏幕上红框数字相互遮挡重叠让你看不清时，绝对不要猜！必须立刻调用此工具获取图标的具体功能含义和准确 ID。"
            },
            handler_func=self._skill_recognize_semantics
        )

        # 2. 布局聚类
        self.register_skill(
            name="analyze_ui_layout",
            schema={
                "name": "analyze_ui_layout",
                "description": "【核心防错工具】面对网页、复杂软件等元素密集的界面时，你直接看图寻找 ID 的错误率极高！在执行点击或输入前，强烈建议先调用此工具，获取当前屏幕的精确 UI 文本结构树，然后从结构树中提取准确无误的 ID。"
            },
            handler_func=self._skill_analyze_ui_layout
        )

        # 3. 找空白区
        self.register_skill(
            name="find_blank_zones",
            schema={
                "name": "find_blank_zones",
                "description": "当你需要点击列表或输入框旁边的空白处时调用此工具生成虚拟 ID。必须先调用 analyze_ui_layout。"
            },
            handler_func=self._skill_find_blank_zones
        )

        # 4. 物理执行
        self.register_skill(
            name="execute_gui_action",
            schema={
                "name": "execute_gui_action",
                "description": "执行最终的 GUI 物理操作。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "next_action": {
                            "type": "string", 
                            # 🌟 核心：在这里把滚轮动作加入枚举列表
                            "enum": [
                                "left_click", "double_click", "right_click", 
                                "type", "type_and_enter", "hotkey", "wait", 
                                "finish", "scroll_down", "scroll_up"
                            ]
                        },
                        "target_id": {"type": "string", "description": "目标数字ID。如果是滚动或快捷键，此项可为空。"},
                        "value": {"type": "string", "description": "输入的文本或快捷键"},
                        "reasoning": {"type": "string", "description": "为什么要执行此动作"}
                    },
                    "required": ["next_action", "reasoning"]
                }
            },
            handler_func=self._skill_execute_gui_action
        )

        # 5. 记忆搜索 (图文大一统)
        self.register_skill(
            name="memory_search",
            schema={
                "name": "memory_search",
                "description": "检索记忆库。它会告诉你以前在这个界面是否成功执行过类似任务，或者是否有常识偏好。",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "当前的任务名称或查询关键词"}},
                    "required": ["query"]
                }
            },
            handler_func=self._skill_memory_search
        )
        
        # 6. 记忆保存
        self.register_skill(
            name="memory_save",
            schema={
                "name": "memory_save",
                "description": "遇到有价值的碎片信息（如用户特定偏好、纠错经验等），保存到长期记忆库供未来参考。",
                "parameters": {
                    "type": "object",
                    "properties": {"content": {"type": "string", "description": "需要长期记住的文本内容"}},
                    "required": ["content"]
                }
            },
            handler_func=lambda args: f"✅ 记忆已存入，ID: {self.memory.add_text_memory(args.get('content'))}"
        )

        # 7. 📖 查阅业务 SOP
        self.register_skill(
            name="read_sop_manual",
            schema={
                "name": "read_sop_manual",
                "description": "当你不知道如何处理特定业务（如：网页搜索、特定软件卸载）时，调用此工具读取标准作业程序(SOP)。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "你想查阅的业务主题英文名，如 'web_search', 'uninstall'"}
                    },
                    "required": ["topic"]
                }
            },
            handler_func=self._skill_read_sop
        )

        # 8. ✍️ 自动撰写 SOP (自我进化)
        self.register_skill(
            name="write_sop_manual",
            schema={
                "name": "write_sop_manual",
                "description": "当你成功摸索出一个复杂业务的完整操作流程时，调用此工具将经验总结为 Markdown 格式的 SOP 文件永久保存，供未来的你直接抄作业。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "业务主题英文简写，必须是纯英文和下划线，例如 'bilibili_search'"},
                        "content": {"type": "string", "description": "SOP 的具体内容，包含严格的分步操作指南（第一步干嘛，第二步干嘛）和避坑注意事项。"}
                    },
                    "required": ["topic", "content"]
                }
            },
            handler_func=self._skill_write_sop
        )


    # ==========================================================
    # ⚙️ 工具执行函数的具体实现
    # ==========================================================

    def _skill_recognize_semantics(self, args):
        print("[Skill] 👁️ 执行深度语义识别...")
        semantics = self.get_som().get_full_screen_semantics(self.ctx.som_base64)
        self.ctx.ui_elements = self.get_som().merge_semantics_to_elements(self.ctx.ui_elements, semantics)
        return "语义识别完成，你可以通过原始截图确认新的功能含义。"

    def _skill_analyze_ui_layout(self, args):
        print("[Skill] 📦 执行布局聚类...")
        self.ctx.current_clusters = self.get_tree().get_clustered_semantics(self.ctx.som_base64, self.ctx.current_task)
        sw, sh = self.ctx.screenshot_obj.size
        fusion = FusionEngine(screen_w=sw, screen_h=sh)
        self.ctx.ui_tree_text = fusion.fuse_clustered_data(self.ctx.ui_elements, self.ctx.current_clusters)
        return f"UI 逻辑结构树如下:\n{self.ctx.ui_tree_text}"
        
    def _skill_find_blank_zones(self, args):
        print("[Skill] 🕳️ 推算可点击空白区...")
        if not self.ctx.current_clusters: return "❌ 错误: 必须先调用 analyze_ui_layout 才能计算空白区。"
        sw, sh = self.ctx.screenshot_obj.size
        fusion = FusionEngine(screen_w=sw, screen_h=sh)
        self.ctx.ui_elements = fusion.inject_blank_zones(self.ctx.ui_elements, self.ctx.current_clusters)
        self.ctx.ui_tree_text = fusion.fuse_clustered_data(self.ctx.ui_elements, self.ctx.current_clusters)
        return f"已生成虚拟空白区 ID。最新 UI 树:\n{self.ctx.ui_tree_text}"

    def _skill_memory_search(self, args):
        query = args.get("query", "")
        print(f"[Skill] 🧠 大模型查阅图文双轨记忆: '{query}'")
        return self.memory.search(query, current_ui_elements=self.ctx.ui_elements)

    def _skill_read_sop(self, args):
        topic = args.get("topic", "")
        print(f"[Skill] 📖 正在查阅业务 SOP: {topic} ...")
        try:
            # 强行指向 skills 文件夹读取 SOP
            sop_loader = PromptLoader(target_dir="skills") 
            # 兼容带前缀或不带前缀的请求
            file_name = f"sop_{topic}.md" if not topic.startswith("sop_") else f"{topic}.md"
            content = sop_loader.load(file_name)
            return f"✅ 找到 {file_name} SOP指南如下:\n\n{content}"
        except FileNotFoundError:
            return f"❌ 抱歉，记忆库中尚未建立关于 '{topic}' 的标准业务操作指南 (SOP)。请依靠常识和视觉分析工具自行摸索，成功后记得调用 write_sop_manual 记录下来。"

    def _skill_write_sop(self, args):
        topic = args.get("topic", "general_task")
        content = args.get("content", "")
        
        # 净化文件名
        safe_topic = re.sub(r'[^a-zA-Z0-9_]', '_', topic.lower())
        file_name = f"sop_{safe_topic}.md" if not safe_topic.startswith("sop_") else f"{safe_topic}.md"
        
        # 定位到 skills 文件夹
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        skills_dir = os.path.join(base_path, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        
        file_path = os.path.join(skills_dir, file_name)
        
        print(f"[Skill] ✍️ Agent 正在自我总结经验，写入 {file_name}...")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# 🤖 Agent OS 自我总结 SOP: {topic}\n\n")
            f.write(content)
            f.write("\n\n---\n*由 Agent OS 自动复盘生成*")
            
        return f"✅ 业务指南已成功生成并存入硬盘！文件名为: {file_name}。你可以在以后的任务中优先调用 read_sop_manual(topic='{safe_topic}') 来抄作业。"

    def _skill_execute_gui_action(self, args):
        # 1. 提取参数
        action = args.get("next_action")
        target_id = args.get("target_id")
        value = args.get("value")
        input_mode = args.get("input_mode", "paste")

        # 2. 只有在需要坐标的动作时才换算，不需要的不强求
        coords = self.get_hand().get_coordinates(target_id, self.ctx.ui_elements, self.ctx.screenshot_obj.size)
        
        # 3. 统一入口执行（Hand 会自己处理滚动、点击、输入、快捷键）
        success = self.get_hand().execute(action, coords, value, input_mode)
        
        if not success and action != "finish":
            return f"❌ 执行 {action} 失败，可能因为 ID {target_id} 无法换算坐标。"
            
        return f"✅ 动作 {action} 已成功执行。"