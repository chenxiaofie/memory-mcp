#!/usr/bin/env python
"""
会话开始时自动创建情景
由 Claude Code SessionStart Hook 调用
"""

import sys
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

# 确保 stdin/stdout 使用 UTF-8 编码
if sys.platform == "win32":
    import io
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 日志文件路径
LOG_FILE = Path(__file__).parent / "hook_debug.log"


def log(message: str):
    """写入调试日志"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except:
        pass


def is_valid_path(path: str) -> bool:
    """检查路径是否有效"""
    try:
        p = Path(path)
        # 尝试检查路径是否存在或可以创建
        return p.exists() or p.parent.exists()
    except (OSError, ValueError):
        return False


def get_parent_pid() -> int:
    """获取父进程 PID（跨平台）- 直接父进程"""
    try:
        import psutil
        return psutil.Process(os.getpid()).ppid()
    except ImportError:
        if sys.platform == "win32":
            return _get_parent_pid_windows(os.getpid())
        else:
            return os.getppid()
    except Exception:
        return 0


def _get_parent_pid_windows(pid: int) -> int:
    """Windows: 获取指定进程的父进程 PID"""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

        if kernel32.Process32First(snapshot, ctypes.byref(pe)):
            while True:
                if pe.th32ProcessID == pid:
                    kernel32.CloseHandle(snapshot)
                    return pe.th32ParentProcessID
                if not kernel32.Process32Next(snapshot, ctypes.byref(pe)):
                    break

        kernel32.CloseHandle(snapshot)
        return 0
    except Exception as e:
        log(f"获取父进程 PID 失败: {e}")
        return 0


def get_claude_or_terminal_pid() -> int:
    """
    向上遍历进程树，找到稳定的终端进程或 IDE 进程
    返回应该被监控的进程 PID

    进程链示例（VS Code 集成终端）：
    code.exe → cmd.exe(终端) → node.exe(Claude Code) → cmd.exe(hook runner) → python.exe

    重要：Claude Code 启动 hook 时会创建临时的 node 子进程，这些进程在 hook 执行完后会退出。
    因此我们需要监控更稳定的进程：终端进程(cmd.exe) 或 IDE 进程(code.exe)。
    """
    try:
        import psutil

        current = psutil.Process(os.getpid())
        ancestors = []

        # 收集所有祖先进程信息
        proc = current
        while proc:
            try:
                parent = proc.parent()
                if parent is None:
                    break

                proc_info = {
                    "pid": parent.pid,
                    "name": parent.name().lower(),
                    "cmdline": " ".join(parent.cmdline()).lower() if parent.cmdline() else "",
                    "create_time": parent.create_time()
                }
                ancestors.append(proc_info)
                log(f"祖先进程: PID={proc_info['pid']}, name={proc_info['name']}, cmdline={proc_info['cmdline'][:100]}")
                proc = parent
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

        if not ancestors:
            log("无法获取祖先进程，使用直接父进程")
            return get_parent_pid()

        # 策略1: 优先查找 IDE 进程（最稳定，VS Code、JetBrains 等）
        # IDE 进程比终端进程更稳定，不会因为 Claude 启动而被替换
        ide_names = {
            "code.exe",  # VS Code
            "idea64.exe", "idea.exe",  # IntelliJ IDEA
            "webstorm64.exe", "webstorm.exe",  # WebStorm
            "pycharm64.exe", "pycharm.exe",  # PyCharm
            "cursor.exe",  # Cursor
        }

        for proc_info in ancestors:
            # 只选择主 IDE 进程，跳过 utility 子进程
            if proc_info["name"] in ide_names:
                cmdline = proc_info["cmdline"]
                # VS Code 主进程命令行不包含 --type=
                if "--type=" not in cmdline:
                    log(f"找到 IDE 主进程: PID={proc_info['pid']}, name={proc_info['name']}")
                    return proc_info["pid"]
                else:
                    log(f"跳过 IDE utility 进程: PID={proc_info['pid']}")

        # 策略2: 查找独立终端进程（Windows Terminal、外部终端等）
        # 注意：VS Code 集成终端的 pwsh.exe 不够稳定，可能会被替换
        standalone_terminal_names = {
            "windowsterminal.exe", "wt.exe",  # Windows Terminal
            # Mac/Linux
            "terminal", "iterm2", "gnome-terminal", "konsole", "alacritty", "kitty"
        }

        for proc_info in ancestors:
            if proc_info["name"] in standalone_terminal_names:
                log(f"找到独立终端进程: PID={proc_info['pid']}, name={proc_info['name']}")
                return proc_info["pid"]

        # 策略3: 查找 Claude Code 主进程（node.exe 运行 claude-code/cli.js）
        node_procs = [p for p in ancestors if "node" in p["name"]]
        for proc_info in node_procs:
            cmdline = proc_info["cmdline"]
            # 只选择 Claude Code 主进程，命令行包含 claude-code
            if "claude-code" in cmdline or "cli.js" in cmdline:
                log(f"找到 Claude Code 主进程: PID={proc_info['pid']}")
                return proc_info["pid"]

        # 策略4: 查找 VS Code 集成终端进程（pwsh.exe/cmd.exe/powershell.exe）
        # 放在最后是因为这些进程可能不够稳定
        integrated_terminal_names = {
            "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
            "bash", "zsh", "fish", "sh"
        }

        for proc_info in ancestors:
            if proc_info["name"] in integrated_terminal_names:
                cmdline = proc_info["cmdline"]
                # 跳过 hook runner 的临时 cmd.exe（命令行包含 /d /s /c 和 python）
                if proc_info["name"] == "cmd.exe":
                    if "/d /s /c" in cmdline and "python" in cmdline:
                        log(f"跳过 hook runner cmd.exe: PID={proc_info['pid']}")
                        continue
                log(f"找到集成终端进程: PID={proc_info['pid']}, name={proc_info['name']}")
                return proc_info["pid"]

        # 策略5: 使用最早创建的 node 进程（兜底）
        if node_procs:
            oldest_node = min(node_procs, key=lambda p: p["create_time"])
            log(f"使用最早的 node 进程（兜底）: PID={oldest_node['pid']}")
            return oldest_node["pid"]

        # 兜底: 返回直接父进程
        log("未找到合适的进程，使用直接父进程")
        return get_parent_pid()

    except ImportError:
        log("psutil 不可用，使用直接父进程")
        return get_parent_pid()
    except Exception as e:
        log(f"查找 Claude/终端进程失败: {e}")
        import traceback
        log(traceback.format_exc())
        return get_parent_pid()


def is_monitor_running(monitor_pid: int) -> bool:
    """检查监控进程是否仍在运行"""
    if monitor_pid <= 0:
        return False

    try:
        import psutil
        proc = psutil.Process(monitor_pid)
        return proc.is_running() and "session_monitor" in proc.cmdline()[-1]
    except ImportError:
        # 简单检查进程是否存在
        if sys.platform == "win32":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {monitor_pid}"],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                return str(monitor_pid) in result.stdout
            except:
                return False
        else:
            try:
                os.kill(monitor_pid, 0)
                return True
            except OSError:
                return False
    except Exception:
        return False


def start_monitor_process(parent_pid: int, project_path: str) -> int:
    """启动监控进程，返回监控进程 PID"""
    monitor_script = Path(__file__).parent / "session_monitor.py"

    if not monitor_script.exists():
        log(f"监控脚本不存在: {monitor_script}")
        return 0

    python_exe = sys.executable

    # Windows: 使用 pythonw.exe 避免弹出窗口
    if sys.platform == "win32":
        pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
        if Path(pythonw_exe).exists():
            python_exe = pythonw_exe

    args = [
        python_exe,
        str(monitor_script),
        "--ppid", str(parent_pid),
        "--project-path", project_path
    ]

    log(f"启动监控进程: {' '.join(args)}")

    try:
        if sys.platform == "win32":
            # Windows: 使用 cmd /c start 启动完全独立的进程
            # 这样可以确保子进程不继承任何句柄
            cmd_args = [
                "cmd", "/c", "start", "/b",
                python_exe,
                str(monitor_script),
                "--ppid", str(parent_pid),
                "--project-path", project_path
            ]

            proc = subprocess.Popen(
                cmd_args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # 等待 cmd 退出（它会立即返回，因为 start /b 是异步的）
            proc.wait()

            # 由于使用 start /b，我们无法获取实际的 PID
            # 但进程已经启动，返回一个占位值
            log(f"监控进程已通过 start /b 启动")
            return 1  # 返回占位值表示成功
        else:
            # Unix: 使用 start_new_session 使进程独立运行
            proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True
            )

            log(f"监控进程已启动，PID: {proc.pid}")
            return proc.pid

    except Exception as e:
        log(f"启动监控进程失败: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        return 0


def save_monitor_pid(project_path: str, monitor_pid: int):
    """将监控进程 PID 保存到活跃情景文件"""
    try:
        episode_file = Path(project_path) / ".claude" / "memory" / "active_episode.json"
        if episode_file.exists():
            with open(episode_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            data["monitor_pid"] = monitor_pid

            with open(episode_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            log(f"监控进程 PID {monitor_pid} 已保存到活跃情景文件")
    except Exception as e:
        log(f"保存监控进程 PID 失败: {e}")


def get_existing_monitor_pid(project_path: str) -> int:
    """从活跃情景文件获取已有的监控进程 PID"""
    try:
        episode_file = Path(project_path) / ".claude" / "memory" / "active_episode.json"
        if episode_file.exists():
            with open(episode_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("monitor_pid", 0)
    except:
        pass
    return 0


def main():
    log("=== SessionStart Hook 开始执行 ===")

    try:
        # 从 stdin 读取 hook 输入
        input_data = sys.stdin.read()
        log(f"stdin 输入: {input_data[:500] if input_data else '(空)'}")

        hook_input = json.loads(input_data) if input_data else {}
        log(f"解析后的 hook_input: {hook_input}")

        # 获取项目路径和会话信息
        cwd_from_hook = hook_input.get("cwd", "")
        session_id = hook_input.get("session_id", "")

        # 优先使用 os.getcwd()，因为 hook 传入的路径可能有编码问题
        actual_cwd = os.getcwd()
        log(f"hook cwd: {cwd_from_hook}")
        log(f"os.getcwd(): {actual_cwd}")

        # 如果 hook 传入的路径有效，使用它；否则使用 os.getcwd()
        if cwd_from_hook and is_valid_path(cwd_from_hook):
            project_path = cwd_from_hook
        else:
            project_path = actual_cwd
            log(f"hook cwd 无效，使用 os.getcwd() 作为 project_path")

        log(f"最终 project_path: {project_path}, session_id: {session_id}")

        # 直接操作 JSON 文件，不导入 MemoryManager/chromadb（避免重型依赖拖慢 hook）
        memory_dir = Path(project_path) / ".claude" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        episode_file = memory_dir / "active_episode.json"

        # 检查是否已有活跃情景
        current_episode = None
        if episode_file.exists():
            try:
                with open(episode_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    current_episode = data.get("episode")
            except (json.JSONDecodeError, IOError):
                pass

        log(f"当前活跃情景: {current_episode}")

        if current_episode:
            # 检查是否过期（超过 30 分钟未活动）
            stale = False
            try:
                created_at = datetime.fromisoformat(current_episode["created_at"])
                stale_minutes = (datetime.now() - created_at).total_seconds() / 60
                if stale_minutes >= 30:
                    stale = True
                    log(f"活跃情景已过期（闲置 {int(stale_minutes)} 分钟），清除并创建新情景")
            except Exception:
                pass

            if not stale:
                # 已有活跃情景且未过期，不重复创建
                log("已有活跃情景，跳过创建")

                # 但仍需确保监控进程在运行
                parent_pid = get_claude_or_terminal_pid()
                if parent_pid > 0:
                    existing_monitor_pid = get_existing_monitor_pid(project_path)
                    if existing_monitor_pid > 0 and is_monitor_running(existing_monitor_pid):
                        log(f"监控进程已在运行 (PID: {existing_monitor_pid})")
                    else:
                        log("监控进程不存在或已退出，启动新的监控进程")
                        monitor_pid = start_monitor_process(parent_pid, project_path)
                        if monitor_pid > 0:
                            save_monitor_pid(project_path, monitor_pid)

                sys.exit(0)

        # 生成情景标题
        project_name = os.path.basename(project_path)
        timestamp = datetime.now().strftime("%m-%d %H:%M")
        title = f"{project_name} 开发会话 {timestamp}"
        log(f"准备创建情景: {title}")

        # 直接创建情景（纯 JSON 操作，不需要向量编码）
        from uuid import uuid4
        episode = {
            "id": f"ep_{uuid4().hex[:8]}",
            "title": title,
            "tags": ["auto", "session", project_name],
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "entity_ids": []
        }
        with open(episode_file, 'w', encoding='utf-8') as f:
            json.dump({"episode": episode, "messages": []}, f, ensure_ascii=False, indent=2)
        log(f"情景创建成功: {episode}")

        # 启动监控进程（监听终端生命周期）
        parent_pid = get_claude_or_terminal_pid()
        log(f"监控目标进程 PID: {parent_pid}")

        if parent_pid > 0:
            # 检查是否已有监控进程在运行
            existing_monitor_pid = get_existing_monitor_pid(project_path)
            if existing_monitor_pid > 0 and is_monitor_running(existing_monitor_pid):
                log(f"监控进程已在运行 (PID: {existing_monitor_pid})，跳过启动")
            else:
                # 启动新的监控进程
                monitor_pid = start_monitor_process(parent_pid, project_path)
                if monitor_pid > 0:
                    save_monitor_pid(project_path, monitor_pid)
        else:
            log("无法获取父进程 PID，跳过启动监控进程")

    except Exception as e:
        log(f"错误: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

    log("=== SessionStart Hook 执行结束 ===\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
