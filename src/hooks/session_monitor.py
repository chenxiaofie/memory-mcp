#!/usr/bin/env python
"""
终端生命周期监控进程
后台运行，监听父进程（终端/Claude Code）的生命周期
当父进程退出时，自动关闭情景

由 session_start.py 在创建情景后启动

职责：
1. 启动时预热向量编码器
2. 监听终端退出
3. 监听关闭信号文件（由 session_end.py 写入）
4. 执行情景关闭（此时编码器已就绪）
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

# 日志文件路径（用户级，始终可写）
LOG_FILE = Path.home() / ".claude" / "memory" / "hook_debug.log"

# 关闭信号文件名
CLOSE_SIGNAL_FILE = ".close_signal"


def log(message: str):
    """写入调试日志"""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] [Monitor] {message}\n")
    except:
        pass


def is_process_alive(pid: int) -> bool:
    """检查进程是否存活（跨平台）"""
    try:
        import psutil
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except ImportError:
        # psutil 不可用时，使用系统命令
        if sys.platform == "win32":
            import subprocess
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                return str(pid) in result.stdout
            except:
                return False
        else:
            # Unix: 发送信号 0 检查进程是否存在
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
    except Exception:
        return False


def get_active_episode_path(project_path: str) -> Path:
    """获取活跃情景文件路径"""
    return Path(project_path) / ".claude" / "memory" / "active_episode.json"


def get_close_signal_path(project_path: str) -> Path:
    """获取关闭信号文件路径"""
    return Path(project_path) / ".claude" / "memory" / CLOSE_SIGNAL_FILE


def check_close_signal(project_path: str) -> dict:
    """
    检查是否有关闭信号文件

    Returns:
        信号内容（dict），如果没有信号则返回 None
    """
    signal_file = get_close_signal_path(project_path)
    if signal_file.exists():
        try:
            with open(signal_file, 'r', encoding='utf-8') as f:
                signal = json.load(f)
            # 读取后删除信号文件
            signal_file.unlink()
            return signal
        except Exception as e:
            log(f"读取关闭信号文件出错: {e}")
            # 删除可能损坏的信号文件
            try:
                signal_file.unlink()
            except:
                pass
    return None


def warmup_encoder():
    """预热向量编码器"""
    log("开始预热向量编码器...")
    try:
        from src.vector.store import start_encoder_warmup, is_encoder_ready
        start_encoder_warmup()
        log("编码器预热任务已启动（后台加载中）")
    except Exception as e:
        log(f"启动编码器预热失败: {e}")


def shutdown_encoder():
    """关闭向量编码器进程池"""
    log("关闭向量编码器进程池...")
    try:
        from src.vector.store import shutdown_encoder as _shutdown
        _shutdown()
        log("编码器进程池已关闭")
    except Exception as e:
        log(f"关闭编码器进程池失败: {e}")


def wait_for_encoder(timeout: float = 60.0) -> bool:
    """等待编码器就绪"""
    try:
        from src.vector.store import is_encoder_ready
        start_time = time.time()
        while not is_encoder_ready():
            if time.time() - start_time > timeout:
                log(f"编码器加载超时（{timeout}秒）")
                return False
            time.sleep(0.5)
        log(f"编码器已就绪，耗时 {time.time() - start_time:.1f}s")
        return True
    except Exception as e:
        log(f"等待编码器就绪时出错: {e}")
        return False


def episode_still_active(project_path: str) -> bool:
    """检查情景是否仍然活跃"""
    try:
        episode_file = get_active_episode_path(project_path)
        if not episode_file.exists():
            return False

        with open(episode_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            episode = data.get("episode")
            return episode is not None and episode.get("status") == "active"
    except Exception as e:
        log(f"检查活跃情景时出错: {e}")
        return False


def get_monitor_pid_from_episode(project_path: str) -> int:
    """从活跃情景文件中获取监控进程 PID"""
    try:
        episode_file = get_active_episode_path(project_path)
        if episode_file.exists():
            with open(episode_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("monitor_pid", 0)
    except:
        pass
    return 0


def close_episode(project_path: str, reason: str = "terminal_closed"):
    """
    关闭情景

    Args:
        project_path: 项目路径
        reason: 关闭原因 (terminal_closed, session_end_signal, etc.)
    """
    log(f"开始关闭情景，项目路径: {project_path}, 原因: {reason}")

    try:
        # 等待编码器就绪（最多等待 60 秒）
        if not wait_for_encoder(timeout=60.0):
            log("警告：编码器未就绪，尝试继续关闭...")

        from src.memory import MemoryManager
        manager = MemoryManager(project_path=project_path)

        current = manager.get_current_episode()
        if not current:
            log("没有活跃情景，无需关闭")
            return

        # 检查是否有消息记录
        if not manager.current_messages:
            # 没有消息的空情景，直接清除不归档
            log("空情景（无消息），直接清除")
            manager.current_episode = None
            manager._save_active_episode()
            return

        # 生成摘要
        summary = generate_summary(manager, reason)
        log(f"生成摘要: {summary[:100]}...")

        # 关闭情景并归档
        manager.close_episode(summary=summary)
        log("情景关闭成功（由监控进程触发）")

    except Exception as e:
        log(f"关闭情景时出错: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())


def generate_summary(manager, reason: str = "terminal_closed") -> str:
    """生成情景摘要"""
    episode = manager.current_episode
    messages = manager.current_messages

    if not episode:
        return ""

    if not messages:
        return f"{episode.get('title', '空会话')} - 无对话记录"

    # 统计信息
    user_count = sum(1 for m in messages if m.get("role") == "user")
    assistant_count = sum(1 for m in messages if m.get("role") == "assistant")

    # 提取用户的主要问题/请求
    user_messages = [m.get("content", "")[:100] for m in messages if m.get("role") == "user"]

    # 根据原因生成不同的关闭说明
    reason_text = {
        "terminal_closed": "[由监控进程自动关闭 - 终端被关闭]",
        "session_end_signal": "[由监控进程关闭 - 收到 SessionEnd 信号]",
    }.get(reason, f"[由监控进程关闭 - {reason}]")

    # 构建摘要
    summary_parts = [
        f"## {episode.get('title', '开发会话')}",
        f"",
        f"**对话统计**: {user_count} 条用户消息, {assistant_count} 条助手回复",
        f"",
        reason_text,
        f"",
        f"**主要话题**:",
    ]

    # 添加用户的前几个问题作为话题
    for i, msg in enumerate(user_messages[:5], 1):
        first_line = msg.split('\n')[0][:80]
        summary_parts.append(f"- {first_line}")

    if len(user_messages) > 5:
        summary_parts.append(f"- ... 等 {len(user_messages) - 5} 条更多")

    # 添加关联的实体
    entity_ids = episode.get("entity_ids", [])
    if entity_ids:
        summary_parts.append(f"")
        summary_parts.append(f"**关联实体**: {len(entity_ids)} 个")

    return "\n".join(summary_parts)


def main():
    parser = argparse.ArgumentParser(description="终端生命周期监控进程")
    parser.add_argument("--ppid", type=int, required=True, help="要监控的父进程 PID")
    parser.add_argument("--project-path", type=str, required=True, help="项目路径")
    args = parser.parse_args()

    parent_pid = args.ppid
    project_path = args.project_path

    log(f"=== 监控进程启动 ===")
    log(f"监控 PID: {os.getpid()}")
    log(f"父进程 PID: {parent_pid}")
    log(f"项目路径: {project_path}")

    # 启动时预热编码器（后台加载，不阻塞）
    warmup_encoder()

    # 检查间隔（秒）
    CHECK_INTERVAL = 2  # 缩短间隔以更快响应信号
    # 父进程退出后的等待时间（秒），给 SessionEnd 信号文件写入机会
    GRACE_PERIOD = 3  # 缩短等待时间，因为现在由监控进程负责关闭

    try:
        while True:
            # 1. 检查是否有关闭信号（由 session_end.py 写入）
            signal = check_close_signal(project_path)
            if signal:
                log(f"收到关闭信号: {signal}")
                if episode_still_active(project_path):
                    close_episode(project_path, reason="session_end_signal")
                else:
                    log("情景已被关闭，跳过")
                break

            # 2. 检查父进程是否存活
            if not is_process_alive(parent_pid):
                log(f"父进程 {parent_pid} 已退出")

                # 等待一小段时间，给 session_end.py 写入信号文件的机会
                log(f"等待 {GRACE_PERIOD} 秒，检查是否有关闭信号...")
                time.sleep(GRACE_PERIOD)

                # 再次检查是否有关闭信号
                signal = check_close_signal(project_path)
                if signal:
                    log(f"收到关闭信号: {signal}")
                    if episode_still_active(project_path):
                        close_episode(project_path, reason="session_end_signal")
                    break

                # 没有信号，直接关闭（终端被强制关闭的情况）
                if episode_still_active(project_path):
                    log("没有收到关闭信号，监控进程直接关闭情景")
                    close_episode(project_path, reason="terminal_closed")
                else:
                    log("情景已被关闭，监控进程退出")

                break

            # 3. 检查情景是否已被关闭（用户可能通过其他方式关闭了）
            if not episode_still_active(project_path):
                log("情景已不再活跃，监控进程退出")
                break

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        log("监控进程被中断")
    except Exception as e:
        log(f"监控进程出错: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
    finally:
        # 关闭编码器进程池，防止子进程变成孤儿进程
        shutdown_encoder()

    log("=== 监控进程结束 ===\n")


if __name__ == "__main__":
    main()
