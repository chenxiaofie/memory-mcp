#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动保存消息 + 自动检索记忆
由 Claude Code Hooks 调用
"""

import sys
import json
import os
import io
import threading

# Hook 超时设置（秒）- 必须小于 Claude Code hook 的 10 秒超时
HOOK_TIMEOUT = 8

# Windows 下设置 stdin/stdout 为 UTF-8 编码
if sys.platform == 'win32':
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from src.memory import MemoryManager
from src.vector import is_encoder_ready


def timeout_handler():
    """超时时强制退出，返回空结果"""
    print(json.dumps({}))
    os._exit(0)


def main():
    # 设置超时保护（使用 threading.Timer 因为 Windows 不支持 signal.alarm）
    timer = threading.Timer(HOOK_TIMEOUT, timeout_handler)
    timer.daemon = True
    timer.start()

    content = ""
    role = "user"
    hook_input = {}  # 初始化，确保后续使用时不会报 NameError

    # 从 stdin 读取 hook 输入（JSON 格式）
    try:
        input_data = sys.stdin.read()
        if input_data:
            hook_input = json.loads(input_data)
            content = hook_input.get("prompt", "")
    except:
        pass

    # 也支持命令行参数（备用）
    if not content and len(sys.argv) >= 3:
        role = sys.argv[1]
        content = sys.argv[2]

    if not content:
        timer.cancel()
        print(json.dumps({}))
        sys.exit(0)

    try:
        # 获取项目路径
        # 优先使用 os.getcwd()，因为 hook 传入的 cwd 在 Windows 上可能有中文编码问题
        actual_cwd = os.getcwd()
        hook_cwd = hook_input.get("cwd", "")
        project_path = actual_cwd or hook_cwd or os.environ.get("CLAUDE_PROJECT_DIR", "")

        # 初始化记忆管理器
        manager = MemoryManager(project_path=project_path)

        # 1. 保存用户消息（这个操作很快，不会阻塞）
        manager.cache_message(role, content)

        # 2. 检查编码器是否就绪，如果没就绪就跳过 recall
        if not is_encoder_ready():
            # 编码器还在加载中，跳过 recall，只保存消息
            timer.cancel()
            print(json.dumps({}))
            sys.exit(0)

        # 3. 检索相关记忆（只在编码器就绪时执行）
        memories = manager.recall(content, top_k=3)

        # 3. 构建上下文
        context_parts = []

        # 添加相关情景
        if memories.get("episodes"):
            context_parts.append("【相关情景记忆】")
            for ep in memories["episodes"][:2]:
                context_parts.append(f"- {ep.get('content', '')[:200]}")

        # 添加相关实体
        if memories.get("entities"):
            context_parts.append("\n【相关知识/决策】")
            for ent in memories["entities"][:3]:
                ent_type = ent.get("metadata", {}).get("type", "")
                context_parts.append(f"- [{ent_type}] {ent.get('content', '')[:150]}")

        # 添加当前情景信息
        current = memories.get("current", {})
        if current.get("episode"):
            context_parts.append(f"\n【当前任务】{current['episode'].get('title', '')}")

        # 如果有记忆，返回上下文
        if context_parts:
            additional_context = "\n".join(context_parts)

            # 返回 hook 输出，添加上下文
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": additional_context
                }
            }
            timer.cancel()
            print(json.dumps(output, ensure_ascii=False))
        else:
            timer.cancel()
            print(json.dumps({}))

    except Exception as e:
        # 出错时不阻塞，静默失败
        timer.cancel()
        print(json.dumps({}))

    sys.exit(0)


if __name__ == "__main__":
    main()
