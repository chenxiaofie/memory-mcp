#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
保存 Assistant 回复到记忆系统
由 Claude Code Stop Hook 调用
"""

import sys
import json
import os
import io

# Windows 下设置 stdin/stdout 为 UTF-8 编码
if sys.platform == 'win32':
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from src.memory import MemoryManager


def extract_last_assistant_message(transcript_path: str) -> str:
    """从 transcript 文件提取最后一条 assistant 消息"""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""

    last_assistant_content = ""

    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    # 查找 assistant 类型的消息
                    if entry.get("type") == "assistant":
                        # 提取文本内容
                        message = entry.get("message", {})
                        content_parts = message.get("content", [])

                        text_parts = []
                        for part in content_parts:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif isinstance(part, str):
                                text_parts.append(part)

                        if text_parts:
                            last_assistant_content = "\n".join(text_parts)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    return last_assistant_content


def main():
    # 从 stdin 读取 hook 输入
    try:
        input_data = sys.stdin.read()
        if not input_data:
            sys.exit(0)

        hook_input = json.loads(input_data)
        transcript_path = hook_input.get("transcript_path", "")

        if not transcript_path:
            sys.exit(0)

        # 提取最后一条 assistant 消息
        content = extract_last_assistant_message(transcript_path)

        if not content:
            sys.exit(0)

        # 限制长度，避免过大
        if len(content) > 5000:
            content = content[:5000] + "\n...[truncated]"

        # 获取项目路径
        # 优先使用 os.getcwd()，因为 hook 传入的 cwd 在 Windows 上可能有中文编码问题
        actual_cwd = os.getcwd()
        hook_cwd = hook_input.get("cwd", "")
        project_path = actual_cwd or hook_cwd or os.environ.get("CLAUDE_PROJECT_DIR", "")

        # 初始化记忆管理器
        manager = MemoryManager(project_path=project_path)

        # 保存 assistant 消息
        manager.cache_message("assistant", content)

    except Exception as e:
        # 出错时静默失败，不阻塞
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
