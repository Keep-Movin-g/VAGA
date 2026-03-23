import json

from core.session import SessionManager
from core.context import RuntimeContext
from core.skills import SkillManager
from core.steering import check_human_steering
from core.llm_client import llm_service
from utils.prompt_loader import PromptLoader

def run_agent_loop_stream(session_id: str, initial_task: str):
    """
    生成器版本的 Agent Loop。
    通过 yield 返回不同类型的字典，供 Streamlit 前端实时渲染。
    """
    session = SessionManager()
    ctx = RuntimeContext()
    skills = SkillManager(ctx)
    loader = PromptLoader()
    
    # 加载主脑思想钢印
    system_prompt = loader.load("brain_planner.md")
    
    # 初始化任务
    if initial_task:
        session.append(session_id, {"role": "user", "content": initial_task})
    
    current_task = initial_task
    needs_user_input = False

    # ================= OUTER LOOP (外层待机循环) =================
    while True:
        has_more_tool_calls = True
        pending_messages = [] 
        
        # 1. 刷新视觉：捕获截图并运行 OmniParser
        # 🌟 告知前端：正在截图
        yield {"type": "status", "content": "📸 正在捕获并分析屏幕..."}
        
        ctx.refresh_vision(current_task if not pending_messages else "人类纠错恢复")
        
        # 🌟 吐出带红框的 SoM 截图给前端显示
        if ctx.som_base64:
            yield {"type": "image", "content": ctx.som_base64}

        # ================= INNER LOOP (大模型核心推演流) =================
        while has_more_tool_calls or pending_messages:
            
            # 处理待处理的消息（如纠错反馈）
            if pending_messages:
                for msg in pending_messages: 
                    session.append(session_id, msg)
                pending_messages.clear()

            # 准备上下文
            history = session.load(session_id)
            messages_for_llm = [{"role": "system", "content": system_prompt}] + history
            
            # 注入多模态图片数据
            if ctx.som_base64:
                clean_b64 = str(ctx.som_base64).split("base64,")[-1].replace('\n', '')
                if messages_for_llm[-1]["role"] == "user":
                    orig_text = messages_for_llm[-1]["content"]
                    messages_for_llm[-1]["content"] = [
                        {"type": "text", "text": orig_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{clean_b64}"}}
                    ]

            # 2. 请求大模型决策
            yield {"type": "status", "content": "🤔 主脑正在统筹下一步策略..."}
            response_msg = llm_service.chat_with_tools(messages_for_llm, tools=skills.get_schemas())
            
            if not response_msg: 
                yield {"type": "text", "role": "system", "content": "❌ 模型未返回任何响应。"}
                break

            # 记录回复
            assistant_record = {"role": "assistant", "content": response_msg.content}
            if hasattr(response_msg, "tool_calls") and response_msg.tool_calls:
                assistant_record["tool_calls"] = response_msg.tool_calls
            session.append(session_id, assistant_record)

            # 🌟 吐出大模型的思考文本
            if response_msg.content:
                yield {"type": "text", "role": "assistant", "content": response_msg.content.strip()}

            # 3. 处理工具调用
            if not hasattr(response_msg, "tool_calls") or not response_msg.tool_calls:
                has_more_tool_calls = False
                needs_user_input = True 
                continue

            for i, tc in enumerate(response_msg.tool_calls):
                func_name = tc.function.name
                args_str = tc.function.arguments
                
                # 🌟 告知前端：正在调用哪个工具
                yield {"type": "tool_start", "name": func_name, "args": args_str}

                # 4. 物理动作拦截与 Steering (人机协作)
                steering_interrupt = None
                if func_name == "execute_gui_action":
                    args = json.loads(args_str) if args_str else {}
                    # 注意：F8/Esc 拦截依然在控制台发生，Streamlit 会处于等待状态
                    steering_interrupt = check_human_steering(ctx, args.get("next_action"), args.get("target_id"), args.get("value"))

                if steering_interrupt:
                    yield {"type": "text", "role": "system", "content": f"🚨 人类拦截: {steering_interrupt}"}
                    pending_messages.append({"role": "user", "content": f"动作被中断。反馈: {steering_interrupt}"})
                    session.append(session_id, {"role": "tool", "tool_call_id": tc.id, "content": "Skipped by human."})
                    break 

                # 5. 正式执行工具
                result = skills.execute(func_name, args_str)
                session.append(session_id, {"role": "tool", "tool_call_id": tc.id, "content": result})
                if func_name == "recognize_semantics":
                    print(f"\n[Debug] 👁️ 语义识别工具返回原始数据:")
                    print(f"┌{'-'*60}┐")
                    # 如果返回的是 JSON 字符串，尝试格式化打印以便阅读
                    try:
                        parsed_res = json.loads(result)
                        print(json.dumps(parsed_res, indent=4, ensure_ascii=False))
                    except:
                        print(result)
                    print(f"└{'-'*60}┘\n")
                
                # 常规的 Tool Output 打印逻辑 (保持你之前的)
                else:
                    display_result = str(result)
                    if len(display_result) > 800:
                        display_result = display_result[:800] + "\n... [已截断] ..."
                    print(f"\n[Tool Output] 🔙 工具 {func_name} 返回结果:")
                    print(f"┌{'-'*60}┐\n{display_result}\n└{'-'*60}┘\n")
                # 🌟 吐出工具执行结果
                yield {"type": "tool_end", "name": func_name, "result": result}
                
                # 6. 成功执行物理动作后的逻辑处理
                if func_name == "execute_gui_action" and "成功" in result:
                    action_args = json.loads(args_str)
                    
                    # 记录图谱记忆 (可选)
                    if ctx.last_state_hash and ctx.current_state_hash:
                        # (此处保持原有的 memory.add_graph_memory 逻辑不变)
                        pass
                    
                    # 判断任务是否终结
                    if action_args.get("next_action") == "finish":
                        yield {"type": "status", "content": "✨ 任务已完成！"}
                        needs_user_input = True
                    else:
                        yield {"type": "status", "content": "🔄 动作已发送，等待界面刷新..."}
                        needs_user_input = False 
                        
                    has_more_tool_calls = False
                    break 

        # ================= 循环控制 =================
        if needs_user_input:
            # 🌟 告知前端：进入等待，停止 Generator
            yield {"type": "wait_user"}
            return 
        else:
            # 继续下一次截图循环
            continue