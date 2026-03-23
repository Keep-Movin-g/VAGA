import streamlit as st
import time
import json
from core.agent_loop import run_agent_loop_stream
import uuid

# --- 1. 页面基础配置 ---
st.set_page_config(
    page_title="Agent OS 驾驶舱",
    page_icon="🤖",
    layout="wide", # 使用宽屏模式，左边看图右边说话
    initial_sidebar_state="expanded"
)

# --- 2. 初始化全局状态 ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_som" not in st.session_state:
    st.session_state.current_som = None

# --- 3. 侧边栏：实时视觉监控 ---
with st.sidebar:
    st.header("🖼️ 实时视觉 (SoM)")
    if st.session_state.current_som:
        st.image(f"data:image/jpeg;base64,{st.session_state.current_som}", use_container_width=True)
    else:
        st.info("等待 Agent 捕获首张截图...")
    
    st.divider()
    if st.button("清理所有对话和日志"):
        st.session_state.chat_history = []
        st.session_state.current_som = None
        st.rerun()

# --- 4. 主界面：对话流 ---
st.title("🤖 Agent OS 控制台")
st.caption("基于 OmniParser + Qwen-VL-Max 的自主 GUI 智能体")

# 渲染历史消息
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "tool" in msg:
            st.caption(f"🛠️ 已执行工具: {msg['tool']}")

# --- 5. 输入框与 Agent 驱动 ---
if prompt := st.chat_input("在此输入您的指令..."):
    # 展示用户消息
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 启动助手响应
    with st.chat_message("assistant"):
        # 创建状态占位符
        status_placeholder = st.empty()
        thought_placeholder = st.empty()
        
        # 核心：驱动生成器
        for step in run_agent_loop_stream(st.session_state.session_id, prompt):
            
            # A. 处理截图更新
            if step["type"] == "image":
                st.session_state.current_som = step["content"]
                # 触发侧边栏图片刷新（Streamlit 机制需要 rerun 或特定处理，这里简单处理）
                # 注意：在大循环中频繁 rerun 会卡顿，我们通常只更新 state 并在 UI 上显示
            
            # B. 处理状态文本
            elif step["type"] == "status":
                status_placeholder.text(f"⏳ {step['content']}")
            
            # C. 处理大模型思考
            elif step["type"] == "text":
                thought_placeholder.markdown(step["content"])
                # 记录到历史
                st.session_state.chat_history.append({"role": "assistant", "content": step["content"]})
            
            # D. 处理工具调用
            elif step["type"] == "tool_start":
                status_placeholder.warning(f"🛠️ 正在调用: {step['name']}...")
            
            elif step["type"] == "tool_end":
                if "execute_gui_action" in step["name"]:
                    status_placeholder.success(f"✅ 动作执行成功: {step['name']}")
                else:
                    # 对于非敏感工具，可以展示简短结果
                    with st.expander(f"查看工具 [{step['name']}] 返回值"):
                        st.write(step["result"])
            
            # E. 任务阶段结束，等待用户
            elif step["type"] == "wait_user":
                status_placeholder.info("✨ 任务已暂停，等待您的下一步指令。")
                break

    # 强制刷新一次界面以展示最终状态
    st.rerun()