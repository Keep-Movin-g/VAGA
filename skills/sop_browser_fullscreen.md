# 🤖 Agent OS 自我总结 SOP: browser_fullscreen

# Browser Fullscreen SOP

## 目标
将当前活动的浏览器窗口（如 Edge, Chrome）切换为全屏模式。

## 操作步骤
1. 确保浏览器窗口是当前活动窗口（点击一下浏览器内部）。
2. 调用 `execute_gui_action` 工具。
3. 设置 `next_action` 为 `hotkey`。
4. 设置 `value` 为 `f11`。
5. 设置 `target_id` 为空（因为是快捷键）。

## 避坑指南
- 不要尝试寻找界面上的“全屏”按钮，不同浏览器位置不同且容易看错。
- 直接使用 F11 系统级快捷键是最通用、最准确的方法。
- 再次按下 F11 即可退出全屏。

---
*由 Agent OS 自动复盘生成*