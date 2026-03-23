import json
from collections.abc import Callable
from typing import cast, Callable
import uuid
from PIL import Image, ImageDraw
import base64
from io import BytesIO

from anthropic import APIResponse
from anthropic.types import ToolResultBlockParam
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaMessageParam, BetaUsage

from agent.llm_utils.oaiclient import run_oai_interleaved
from agent.llm_utils.groqclient import run_groq_interleaved
from agent.llm_utils.utils import is_image_path
import time
import re

OUTPUT_DIR = "./tmp/outputs"

def extract_data(input_string, data_type):
    # Regular expression to extract content starting from '```python' until the end if there are no closing backticks
    #这是一个健壮的 **Parser（解析器）工具函数**，专门用于清洗 LLM 的输出，确保后续的 `json.loads()` 不会因为遇到 Markdown 符号（```）或额外的解释性文字而报错
    pattern = f"```{data_type}" + r"(.*?)(```|$)"
    # Extract content
    # re.DOTALL allows '.' to match newlines as well
    matches = re.findall(pattern, input_string, re.DOTALL)
    # Return the first match if exists, trimming whitespace and ignoring potential closing backticks
    return matches[0][0].strip() if matches else input_string

class VLMAgent:
    def __init__(
        self,
        model: str, 
        provider: str, 
        api_key: str,
        output_callback: Callable, 
        api_response_callback: Callable,
        max_tokens: int = 4096,
        only_n_most_recent_images: int | None = None,
        print_usage: bool = True,
    ):
        if model == "omniparser + gpt-4o":
            self.model = "gpt-4o-2024-11-20"
        elif model == "omniparser + R1":
            self.model = "deepseek-r1-distill-llama-70b"
        elif model == "omniparser + qwen3":
            self.model = "qwen3.5-flash"
        elif model == "omniparser + o1":
            self.model = "o1"
        elif model == "omniparser + o3-mini":
            self.model = "o3-mini"
        else:
            raise ValueError(f"Model {model} not supported")
        

        self.provider = provider
        self.api_key = api_key
        self.api_response_callback = api_response_callback
        self.max_tokens = max_tokens
        self.only_n_most_recent_images = only_n_most_recent_images
        self.output_callback = output_callback

        self.print_usage = print_usage
        self.total_token_usage = 0
        self.total_cost = 0
        self.step_count = 0

        self.system = ''
           
    def __call__(self, messages: list, parsed_screen: list[str, list, dict]):
        self.step_count += 1
        image_base64 = parsed_screen['original_screenshot_base64']
        latency_omniparser = parsed_screen['latency']
        self.output_callback(f'-- Step {self.step_count}: --', sender="bot")
        screen_info = str(parsed_screen['screen_info'])
        screenshot_uuid = parsed_screen['screenshot_uuid']
        screen_width, screen_height = parsed_screen['width'], parsed_screen['height']

        boxids_and_labels = parsed_screen["screen_info"]
        system = self._get_system_prompt(boxids_and_labels)

        # drop looping actions msg, byte image etc
        #这段代码是 “上下文瘦身（Context Pruning）” 机制，目的是在多轮对话中减少发给大模型的图片数量，以节省 Token 费用并防止超出上下文窗口限制。
        planner_messages = messages
        _remove_som_images(planner_messages)#遍历历史聊天记录，删除所有 SOM 图片（Set-of-Mark，即画满红框和数字 ID 的截图）。当模型根据这张图做完决策（比如“点击 ID 5”）后，这张花哨的图在历史记录里就没用了
        _maybe_filter_to_n_most_recent_images(planner_messages, self.only_n_most_recent_images)#只保留最近 N 张截图（包括原始截图
    #，其核心目的是构建并注入当前步骤的视觉上下文（Image Context Injection），以便大模型（VLM）能够“看见”最新的屏幕状态。（构建当前步骤的视觉上下文）
        '''
        背景： 大模型的消息（Messages）通常有两种格式：
        纯文本格式（旧/简单）： {"role": "user", "content": "你好"}
        多模态格式（新/复杂）： {"role": "user", "content": [{"type": "text", "text": "你好"}, {"type": "image_url", ...}]}
        逻辑： 如果最后一条消息的 content 只是一个字符串（比如 System Prompt 或用户的纯文本指令），
        这里会把它强制转换成一个列表（List）。这样后续就可以用 .append() 方法往里面塞图片了，而不会报错。
        '''
        if isinstance(planner_messages[-1], dict):
            if not isinstance(planner_messages[-1]["content"], list):
                planner_messages[-1]["content"] = [planner_messages[-1]["content"]]
            planner_messages[-1]["content"].append(f"{OUTPUT_DIR}/screenshot_{screenshot_uuid}.png")#原始截图
            planner_messages[-1]["content"].append(f"{OUTPUT_DIR}/screenshot_som_{screenshot_uuid}.png")#SOM 图，加上画满红框和数字 ID 的截图

        start = time.time()
        if "gpt" in self.model or "o1" in self.model or "o3-mini" in self.model:
            vlm_response, token_usage = run_oai_interleaved(#会检测到这字符串是图片路径，然后读取文件并转为 Base64 发送给 GPT-4o。
                messages=planner_messages,#构建好的视觉上下文
                system=system,#系统提示
                model_name=self.model,#模型名称
                api_key=self.api_key,#API 密钥
                max_tokens=self.max_tokens,#最大 Token 数
                provider_base_url="https://api.openai.com/v1",#OpenAI 的 API 地址
                temperature=0,#温度参数
            )
            print(f"oai token usage: {token_usage}")#打印 Token 使用情况    
            self.total_token_usage += token_usage
            if 'gpt' in self.model:
                self.total_cost += (token_usage * 2.5 / 1000000)  # https://openai.com/api/pricing/
                #计算 Token 使用费用
            elif 'o1' in self.model:
                self.total_cost += (token_usage * 15 / 1000000)  # https://openai.com/api/pricing/
            elif 'o3-mini' in self.model:#计算 Token 使用费用
                self.total_cost += (token_usage * 1.1 / 1000000)  # https://openai.com/api/pricing/
        elif "r1" in self.model:
            vlm_response, token_usage = run_groq_interleaved(#代码中会过滤掉这些图片路径，只发文本描述。
                system=system,
                model_name=self.model,
                api_key=self.api_key,
                max_tokens=self.max_tokens,
            )
            print(f"groq token usage: {token_usage}")#打印 Token 使用情况
            self.total_token_usage += token_usage
            self.total_cost += (token_usage * 0.99 / 1000000)#计算 Token 使用费用
        elif "qwen" in self.model:
            vlm_response, token_usage = run_oai_interleaved(#会检测到这字符串是图片路径，然后读取文件并转为 Base64 发送给 GPT-4o
                messages=planner_messages,
                system=system,
                model_name=self.model,#模型名称
                api_key=self.api_key,#API 密钥
                max_tokens=min(2048, self.max_tokens),#最大 Token 数
                provider_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",#阿里云的 API 地址
                temperature=0,#温度参数
            )
            print(f"qwen token usage: {token_usage}")
            self.total_token_usage += token_usage
            self.total_cost += (token_usage * 2.2 / 1000000)  # https://help.aliyun.com/zh/model-studio/getting-started/models?spm=a2c4g.11186623.0.0.74b04823CGnPv7#fe96cfb1a422a
        else:
            raise ValueError(f"Model {self.model} not supported")
        latency_vlm = time.time() - start
        self.output_callback(f"LLM: {latency_vlm:.2f}s, OmniParser: {latency_omniparser:.2f}s", sender="bot")#打印模型响应时间

        print(f"{vlm_response}")#打印模型响应
        
        if self.print_usage:
            print(f"Total token so far: {self.total_token_usage}. Total cost so far: $USD{self.total_cost:.5f}")
        
        vlm_response_json = extract_data(vlm_response, "json")
        vlm_response_json = json.loads(vlm_response_json)

        img_to_show_base64 = parsed_screen["som_image_base64"]#SOM 图
        if "Box ID" in vlm_response_json:#如果模型响应中包含 Box ID，则绘制框
            try:
                #把 AI 选中的 ID 翻译成具体的点击位置，并在图上画个靶心给用户看
                ## 1. 查表：根据 ID 找到对应的边界框 (bbox)
                # bbox 通常是 [x_min, y_min, x_max, y_max] 的比例坐标 (0.0 - 1.0)
                bbox = parsed_screen["parsed_content_list"][int(vlm_response_json["Box ID"])]["bbox"]
                # 2. 算中心点：计算框的中心位置，并乘上屏幕分辨率，转回绝对像素
                # (x_min + x_max) / 2 = 中心点比例 x
                # 中心点比例 x * 屏幕宽度 = 实际像素 x
                #它把抽象的“第几个盒子”变成了具体的“屏幕第几行第几列的像素点”，后续 computer.py 里的 mouse_move 就靠这个坐标去移动鼠标。
                vlm_response_json["box_centroid_coordinate"] = [int((bbox[0] + bbox[2]) / 2 * screen_width), int((bbox[1] + bbox[3]) / 2 * screen_height)]
                img_to_show_data = base64.b64decode(img_to_show_base64)
                img_to_show = Image.open(BytesIO(img_to_show_data))
                # 光算出坐标还不够，Agent 需要在界面上给用户展示它打算点哪里，让用户有“掌控感”
                # 3. 画靶心：用红色圆圈标记中心点，外加一圈更粗的红圈，让用户一眼就能看到
                ## 3. 准备画板
                draw = ImageDraw.Draw(img_to_show)
                x, y = vlm_response_json["box_centroid_coordinate"] 
                ## 4. 画靶心 (Bullseye)
                radius = 10
                # 画一个实心的红点
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill='red')
                # 画一个空心的红圈（在红点外面再画一圈，形成类似靶子的效果）
                draw.ellipse((x - radius*3, y - radius*3, x + radius*3, y + radius*3), fill=None, outline='red', width=2)

                buffered = BytesIO()
                img_to_show.save(buffered, format="PNG")
                img_to_show_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            except:
                print(f"Error parsing: {vlm_response_json}")
                pass
        # self.output_callback(f'<img src="data:image/png;base64,{img_to_show_base64}">', sender="bot")#生成的图片（带有红圈标记的截图）发送给前端界面进行展示。
        #展示解析后的屏幕元素列表，让用户直观看到 AI 看到的内容。
        #output_callback 是一个回调函数（Callback Function），它是连接**后端逻辑（Agent）与前端界面（UI）**的桥梁。
        #保持界面整洁，但如果你想看细节，点一下也能看到
        # 注释掉：不再打印屏幕元素列表信息
        self.output_callback(
                    f'<details>'
                    f'  <summary>Parsed Screen elemetns by OmniParser</summary>'
                    f'  <pre>{screen_info}</pre>'
                    f'</details>',
                    sender="bot"
                )
        vlm_plan_str = ""
        for key, value in vlm_response_json.items():
            if key == "Reasoning":
                vlm_plan_str += f'{value}'
            else:
                vlm_plan_str += f'\n{key}: {value}'

        # construct the response so that anthropicExcutor can execute the tool
        #，其核心目的是将通用大模型（GPT-4o, R1）输出的 JSON 决策“伪装”成 Anthropic 官方定义的 Tool Use 格式。
        #首先创建一个 BetaTextBlock。这相当于告诉执行器：“这是 AI 的思考过程（Reasoning）”，执行器会将其记录在对话历史中，但在屏幕上只是显示文字，不执行动作。
        response_content = [BetaTextBlock(text=vlm_plan_str, type='text')]
        #如果模型决策中包含坐标（说明要操作某个位置），代码会自动在点击之前插入一个 mouse_move 动作。
        if 'box_centroid_coordinate' in vlm_response_json:
            move_cursor_block = BetaToolUseBlock(id=f'toolu_{uuid.uuid4()}',
                                            input={'action': 'mouse_move', 'coordinate': vlm_response_json["box_centroid_coordinate"]},
                                            name='computer', type='tool_use')
            response_content.append(move_cursor_block)
        #转换核心动作 (Action Translation) 接下来的 if/elif/else 块负责将 JSON 中的 Next Action 映射为具体的工具调用：（将 AI 的决策转换成具体的动作指令）
        if vlm_response_json["Next Action"] == "None":
            print("Task paused/completed.")
        #打字 (type)：如果动作是打字，就把 JSON 里的 value 字段提取出来，构造一个带有 text 参数的工具调用。
        elif vlm_response_json["Next Action"] == "type":
            sim_content_block = BetaToolUseBlock(id=f'toolu_{uuid.uuid4()}',
                                        input={'action': vlm_response_json["Next Action"], 'text': vlm_response_json["value"]},
                                        name='computer', type='tool_use')
            response_content.append(sim_content_block)
        else:
            #对于 left_click, scroll_down 等不需要额外参数的动作，直接构造工具调用。
            sim_content_block = BetaToolUseBlock(id=f'toolu_{uuid.uuid4()}',
                                            input={'action': vlm_response_json["Next Action"]},
                                            name='computer', type='tool_use')
            response_content.append(sim_content_block)
        #这个对象会被返回给 loop.py，然后传给 executor。executor 收到后会以为这是 Claude 发出的指令，从而正常驱动 computer.py 操作电脑。
        # response_message = BetaMessage(id=f'toolu_{uuid.uuid4()}', content=response_content, model='', role='assistant', type='message', stop_reason='tool_use', usage=BetaUsage(input_tokens=0, output_tokens=0))
        return response_content, vlm_response_json

    def _api_response_callback(self, response: APIResponse):
        self.api_response_callback(response)

    def _get_system_prompt(self, screen_info: str = ""):
        main_section = f"""
You are using a Windows device.
You are able to use a mouse and keyboard to interact with the computer based on the given task and screenshot.
You can only interact with the desktop GUI (no terminal or application menu access).

You may be given some history plan and actions, this is the response from the previous loop.
You should carefully consider your plan base on the task, screenshot, and history actions.

Here is the list of all detected bounding boxes by IDs on the screen and their description:{screen_info}

Your available "Next Action" only include:
- type: types a string of text.
- left_click: move mouse to box id and left clicks.
- right_click: move mouse to box id and right clicks.
- double_click: move mouse to box id and double clicks.
- hover: move mouse to box id.
- scroll_up: scrolls the screen up to view previous content.
- scroll_down: scrolls the screen down, when the desired button is not visible, or you need to see more content. 
- wait: waits for 1 second for the device to load or respond.

Based on the visual information from the screenshot image and the detected bounding boxes, please determine the next action, the Box ID you should operate on (if action is one of 'type', 'hover', 'scroll_up', 'scroll_down', 'wait', there should be no Box ID field), and the value (if the action is 'type') in order to complete the task.

Output format:
```json
{{
    "Reasoning": str, # describe what is in the current screen, taking into account the history, then describe your step-by-step thoughts on how to achieve the task, choose one action from available actions at a time.
    "Next Action": "action_type, action description" | "None" # one action at a time, describe it in short and precisely. 
    "Box ID": n,
    "value": "xxx" # only provide value field if the action is type, else don't include value key
}}
```

One Example:
```json
{{  
    "Reasoning": "The current screen shows google result of amazon, in previous action I have searched amazon on google. Then I need to click on the first search results to go to amazon.com.",
    "Next Action": "left_click",
    "Box ID": m
}}
```

Another Example:
```json
{{
    "Reasoning": "The current screen shows the front page of amazon. There is no previous action. Therefore I need to type "Apple watch" in the search bar.",
    "Next Action": "type",
    "Box ID": n,
    "value": "Apple watch"
}}
```

Another Example:
```json
{{
    "Reasoning": "The current screen does not show 'submit' button, I need to scroll down to see if the button is available.",
    "Next Action": "scroll_down",
}}
```

IMPORTANT NOTES:
1. You should only give a single action at a time.

IMPORTANT GUIDELINES:
1. IGNORE CODE EDITORS: The current screen may contain a code editor (like VS Code, Cursor, or PyCharm). 
   DO NOT interact with any elements inside the code editor (e.g., file tabs, terminal, code lines). 
   Focus ONLY on the system desktop, taskbar, or browser windows.
2. HOW TO START APPS: To open an application from the desktop, you MUST use 'double_click'. 
   To open from the taskbar, use 'left_click'.
3. TYPING: When you use the 'type' action, the system will automatically press 'Enter' for you. 
   Do not perform a separate click for the Enter key.
4. TASK COMPLETION: If you see the goal is achieved (e.g., Bilibili is open and showing search results), 
   set 'Next Action' to 'None'.
5. TYPING: 
   - When you want to input text, use the 'type' action DIRECTLY. 
   - **DO NOT perform a separate 'left_click' to focus the box first.** The 'type' action automatically handles clicking.
   - If you see the target input box, just 'type'.

6. AVOID WAITING:
   - If the target app (e.g., Edge) is visible, **DO NOT WAIT** to check for "maximize" or "load" unless the screen is completely blank.
   - Proceed to interact with the app immediately.

7. WINDOW STATE:
   - Do not obsess over maximizing the window. If you see the element you need (e.g., search bar), interact with it regardless of window size.
"""
        thinking_model = "r1" in self.model
        if not thinking_model:
            main_section += """
2. You should give an analysis to the current screen, and reflect on what has been done by looking at the history, then describe your step-by-step thoughts on how to achieve the task.

"""
        else:
            main_section += """
2. In <think> XML tags give an analysis to the current screen, and reflect on what has been done by looking at the history, then describe your step-by-step thoughts on how to achieve the task. In <output> XML tags put the next action prediction JSON.

"""
        main_section += """
3. Attach the next action prediction in the "Next Action".
4. You should not include other actions, such as keyboard shortcuts.
5. When the task is completed, don't complete additional actions. You should say "Next Action": "None" in the json field.
6. The tasks involve buying multiple products or navigating through multiple pages. You should break it into subgoals and complete each subgoal one by one in the order of the instructions.
7. avoid choosing the same action/elements multiple times in a row, if it happens, reflect to yourself, what may have gone wrong, and predict a different action.
8. If you are prompted with login information page or captcha page, or you think it need user's permission to do the next action, you should say "Next Action": "None" in the json field.
""" 

        return main_section

def _remove_som_images(messages):
    for msg in messages:
        msg_content = msg["content"]
        if isinstance(msg_content, list):
            msg["content"] = [
                cnt for cnt in msg_content 
                if not (isinstance(cnt, str) and 'som' in cnt and is_image_path(cnt))
            ]


def _maybe_filter_to_n_most_recent_images(
    messages: list[BetaMessageParam],
    images_to_keep: int,
    min_removal_threshold: int = 10,
):
    """
    With the assumption that images are screenshots that are of diminishing value as
    the conversation progresses, remove all but the final `images_to_keep` tool_result
    images in place
    """
    if images_to_keep is None:
        return messages
    #代码首先遍历整个消息列表，统计目前历史记录里总共有多少张图片。
    total_images = 0
    for msg in messages:
        for cnt in msg.get("content", []):
            # 统计类型 1：字符串路径形式的图片（OmniParser VLM 模式常用）
            if isinstance(cnt, str) and is_image_path(cnt):
                total_images += 1
                # 统计类型 2：Anthropic 格式的工具返回图片（tool_result）
            elif isinstance(cnt, dict) and cnt.get("type") == "tool_result":
                for content in cnt.get("content", []):
                    if isinstance(content, dict) and content.get("type") == "image":
                        total_images += 1

    images_to_remove = total_images - images_to_keep
    #代码再次遍历消息列表，从最早的消息开始，逐个删除图片，直到删够了数量为止。
    for msg in messages:
        msg_content = msg["content"]
        if isinstance(msg_content, list):
            new_content = []
            for cnt in msg_content:
                # Remove images from SOM or screenshot as needed
                ## 如果遇到图片路径字符串，并且还没删够，就跳过这张图，继续删下一张。
                if isinstance(cnt, str) and is_image_path(cnt):
                    if images_to_remove > 0:
                        images_to_remove -= 1
                        continue
                # 如果遇到 Anthropic 的工具返回结果
                # VLM shouldn't use anthropic screenshot tool so shouldn't have these but in case it does, remove as needed
                elif isinstance(cnt, dict) and cnt.get("type") == "tool_result":
                    new_tool_result_content = []
                    #进入内部，只删除 image 类型的 entry，保留 text 类型的 entry（如报错信息）
                    for tool_result_entry in cnt.get("content", []):
                        if isinstance(tool_result_entry, dict) and tool_result_entry.get("type") == "image":
                            if images_to_remove > 0:
                                images_to_remove -= 1
                                continue
                        new_tool_result_content.append(tool_result_entry)
                    cnt["content"] = new_tool_result_content
                # Append fixed content to current message's content list
                new_content.append(cnt)
            msg["content"] = new_content