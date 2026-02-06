#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
会话结束时发送关闭信号给监控进程
由 Claude Code SessionEnd Hook 调用

注意：不再直接关闭情景，而是写入信号文件，由监控进程处理。
这样可以复用监控进程中已加载的向量编码器。
"""

import sys
import json
import os
import io
from datetime import datetime
from pathlib import Path

# Windows 下设置 stdin/stdout 为 UTF-8 编码
if sys.platform == 'win32':
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 日志文件路径（和 session_start.py 共用同一个日志）
LOG_FILE = Path(__file__).parent / "hook_debug.log"

# 关闭信号文件名（与 session_monitor.py 保持一致）
CLOSE_SIGNAL_FILE = ".close_signal"


def log(message: str):
    """写入调试日志"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] [SessionEnd] {message}\n")
    except:
        pass


def get_close_signal_path(project_path: str) -> Path:
    """获取关闭信号文件路径"""
    return Path(project_path) / ".claude" / "memory" / CLOSE_SIGNAL_FILE


def write_close_signal(project_path: str, reason: str = "session_end"):
    """写入关闭信号文件"""
    signal_file = get_close_signal_path(project_path)
    signal_file.parent.mkdir(parents=True, exist_ok=True)

    signal = {
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "pid": os.getpid()
    }

    with open(signal_file, 'w', encoding='utf-8') as f:
        json.dump(signal, f, ensure_ascii=False)

    log(f"关闭信号已写入: {signal_file}")


def episode_still_active(project_path: str) -> bool:
    """检查情景是否仍然活跃"""
    try:
        episode_file = Path(project_path) / ".claude" / "memory" / "active_episode.json"
        if not episode_file.exists():
            return False

        with open(episode_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            episode = data.get("episode")
            return episode is not None and episode.get("status") == "active"
    except Exception:
        return False


def remove_company_trust():
    """
    移除 Company 目录的信任状态
    这是一个 workaround，因为 Claude Code 在 trusted 目录下执行 hooks 时会卡住
    """
    try:
        claude_json = Path.home() / ".claude.json"
        if not claude_json.exists():
            return

        with open(claude_json, 'r', encoding='utf-8') as f:
            data = json.load(f)

        projects = data.get('projects', {})
        keys_to_remove = [k for k in projects.keys() if 'Company' in k]

        if not keys_to_remove:
            return

        for k in keys_to_remove:
            del projects[k]

        with open(claude_json, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        log(f"已移除 Company 目录的信任状态: {keys_to_remove}")
    except Exception as e:
        log(f"移除信任状态失败: {e}")


def main():
    log("=== SessionEnd Hook 开始执行 ===")

    try:
        # 从 stdin 读取 hook 输入
        input_data = sys.stdin.read()
        log(f"stdin 输入: {input_data[:500] if input_data else '(空)'}")

        hook_input = json.loads(input_data) if input_data else {}
        log(f"解析后的 hook_input: {hook_input}")

        # 获取项目路径 - 优先使用 os.getcwd()，因为 hook 传入的 cwd 在 Windows 上可能有中文编码问题
        hook_cwd = hook_input.get("cwd", "")
        actual_cwd = os.getcwd()
        log(f"hook cwd: {hook_cwd}")
        log(f"os.getcwd(): {actual_cwd}")

        # 优先使用 os.getcwd()，它能正确处理中文路径
        project_path = actual_cwd or hook_cwd or os.environ.get("CLAUDE_PROJECT_DIR", "")
        log(f"最终 project_path: {project_path}")

        # 检查是否有活跃情景
        if not episode_still_active(project_path):
            log("没有活跃情景，无需发送关闭信号")
            sys.exit(0)

        # 写入关闭信号，由监控进程处理
        reason = hook_input.get("reason", "session_end")
        write_close_signal(project_path, reason=reason)
        log(f"关闭信号已发送，原因: {reason}")

    except Exception as e:
        log(f"错误: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

    # Workaround: 移除 Company 目录的信任状态，避免下次启动时 hooks 卡住
    remove_company_trust()

    log("=== SessionEnd Hook 执行结束 ===\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
