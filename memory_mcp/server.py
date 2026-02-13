"""
MCP 记忆服务入口
实现情景+实体记忆的 MCP 服务
"""

import os
import sys
import json
import asyncio
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    Resource,
    ResourceTemplate,
)

from .memory import MemoryManager




# ==================== 父进程监控 ====================

_parent_monitor_task = None


async def monitor_parent_process():
    """
    监控父进程是否存活。
    如果父进程死亡（变成孤儿进程），自动退出。
    这解决了 Claude 进程结束后 MCP 进程变成僵尸的问题。
    """
    import signal

    parent_pid = os.getppid()
    print(f"[memory-mcp] Monitoring parent process (PID: {parent_pid})", file=sys.stderr)

    while True:
        await asyncio.sleep(5)  # 每 5 秒检查一次

        try:
            if sys.platform == 'win32':
                # Windows: 检查父进程是否存在
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, parent_pid)
                if handle == 0:
                    # 进程不存在
                    print(f"[memory-mcp] Parent process {parent_pid} died. Exiting.", file=sys.stderr)
                    os._exit(0)
                else:
                    kernel32.CloseHandle(handle)
            else:
                # Unix: 如果 ppid 变成 1（init），说明原父进程已死
                current_ppid = os.getppid()
                if current_ppid != parent_pid or current_ppid == 1:
                    print(f"[memory-mcp] Parent process {parent_pid} died (now {current_ppid}). Exiting.", file=sys.stderr)
                    os._exit(0)
        except Exception as e:
            print(f"[memory-mcp] Parent monitor error: {e}", file=sys.stderr)


def start_parent_monitor():
    """在后台启动父进程监控"""
    global _parent_monitor_task

    def run_monitor():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(monitor_parent_process())

    import threading
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()


# 创建 MCP 服务实例
server = Server("memory-mcp")

# 记忆管理器（延迟初始化，带锁保护）
import threading
_manager_lock = threading.Lock()
memory_manager: MemoryManager = None


def get_manager() -> MemoryManager:
    """获取记忆管理器实例（线程安全）"""
    global memory_manager
    if memory_manager is None:
        with _manager_lock:
            # 双重检查锁定
            if memory_manager is None:
                project_path = os.environ.get("CLAUDE_PROJECT_ROOT", os.getcwd())
                memory_manager = MemoryManager(project_path=project_path)
    return memory_manager


# ==================== 工具定义 ====================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用工具"""
    return [
        # 消息缓存
        Tool(
            name="memory_cache_message",
            description="缓存一条消息到记忆系统（自动检测实体候选）",
            inputSchema={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "消息角色: user 或 assistant",
                        "enum": ["user", "assistant"]
                    },
                    "content": {
                        "type": "string",
                        "description": "消息内容"
                    }
                },
                "required": ["role", "content"]
            }
        ),

        # 情景管理
        Tool(
            name="memory_start_episode",
            description="开始一个新的情景（任务/功能开发会话）",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "情景标题，如：登录功能开发"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表，如：[\"auth\", \"login\"]"
                    }
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="memory_close_episode",
            description="关闭当前情景，生成摘要并归档",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "可选的自定义摘要，不提供则自动生成"
                    }
                }
            }
        ),
        Tool(
            name="memory_get_current_episode",
            description="获取当前活跃的情景信息",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        # 实体管理
        Tool(
            name="memory_add_entity",
            description="添加一个实体（Decision/Preference/Concept/Habit/File/Architecture）",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "实体类型",
                        "enum": ["Decision", "Preference", "Concept", "Habit", "File", "Architecture"]
                    },
                    "content": {
                        "type": "string",
                        "description": "实体内容"
                    },
                    "reason": {
                        "type": "string",
                        "description": "可选的原因说明"
                    }
                },
                "required": ["entity_type", "content"]
            }
        ),
        Tool(
            name="memory_confirm_entity",
            description="确认一个待确认的实体候选",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "候选实体 ID"
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "确认的实体类型"
                    },
                    "content": {
                        "type": "string",
                        "description": "实体内容（可修改）"
                    }
                },
                "required": ["candidate_id", "entity_type", "content"]
            }
        ),
        Tool(
            name="memory_reject_candidate",
            description="拒绝一个误判的实体候选",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "候选实体 ID"
                    }
                },
                "required": ["candidate_id"]
            }
        ),
        Tool(
            name="memory_deprecate_entity",
            description="废弃一个过时的实体",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "实体 ID"
                    },
                    "superseded_by": {
                        "type": "string",
                        "description": "取代此实体的新实体 ID"
                    }
                },
                "required": ["entity_id"]
            }
        ),
        Tool(
            name="memory_get_pending",
            description="获取所有待确认的实体候选",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        # 检索
        Tool(
            name="memory_recall",
            description="综合检索记忆（情景+实体）。【重要】当用户询问'我是谁'、身份信息、个人偏好、历史决策、之前讨论过的内容时，应主动调用此工具检索相关记忆，而不是凭空回答。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索查询"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 5
                    },
                    "include_deprecated": {
                        "type": "boolean",
                        "description": "是否包含已废弃的实体",
                        "default": False
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memory_search_by_type",
            description="按类型检索实体",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "实体类型",
                        "enum": ["Decision", "Preference", "Concept", "Habit", "File", "Architecture", "Episode"]
                    },
                    "query": {
                        "type": "string",
                        "description": "可选的检索查询"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 10
                    }
                },
                "required": ["entity_type"]
            }
        ),
        Tool(
            name="memory_get_episode_detail",
            description="获取情景详情（包含消息和关联实体）",
            inputSchema={
                "type": "object",
                "properties": {
                    "episode_id": {
                        "type": "string",
                        "description": "情景 ID"
                    }
                },
                "required": ["episode_id"]
            }
        ),

        # 统计
        Tool(
            name="memory_stats",
            description="获取记忆系统统计信息",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        # 编码器状态
        Tool(
            name="memory_encoder_status",
            description="查询向量编码器状态。返回编码器是否已就绪，以及哪些操作当前可用。",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        # 日志管理
        Tool(
            name="memory_clear_cache",
            description="清空消息缓存日志（message_cache.jsonl）。警告：此操作不可逆！",
            inputSchema={
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "确认清空，必须设为 true",
                        "default": False
                    }
                },
                "required": ["confirm"]
            }
        ),
        Tool(
            name="memory_cleanup_messages",
            description="清理超过指定天数的消息缓存，保留最近 N 天的消息",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "保留最近 N 天的消息",
                        "default": 7
                    }
                }
            }
        ),
        Tool(
            name="memory_list_episodes",
            description="列出所有历史情景（按时间排序，不依赖语义搜索）。当用户要查看'所有历史情景'时使用此工具，避免语义搜索遗漏。",
            inputSchema={
                "type": "object",
                "properties": {
                    "order": {
                        "type": "string",
                        "description": "排序方式：desc（最新在前）或 asc（最早在前）",
                        "enum": ["desc", "asc"],
                        "default": "desc"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 50
                    }
                }
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """调用工具"""
    manager = get_manager()

    try:
        if name == "memory_cache_message":
            result = manager.cache_message(
                role=arguments["role"],
                content=arguments["content"]
            )

        elif name == "memory_start_episode":
            result = manager.start_episode(
                title=arguments["title"],
                tags=arguments.get("tags", [])
            )

        elif name == "memory_close_episode":
            result = manager.close_episode(
                summary=arguments.get("summary")
            )

        elif name == "memory_get_current_episode":
            result = manager.get_current_episode()

        elif name == "memory_add_entity":
            result = manager.add_entity(
                entity_type=arguments["entity_type"],
                content=arguments["content"],
                reason=arguments.get("reason")
            )

        elif name == "memory_confirm_entity":
            result = manager.confirm_entity(
                candidate_id=arguments["candidate_id"],
                entity_type=arguments["entity_type"],
                content=arguments["content"]
            )

        elif name == "memory_reject_candidate":
            manager.reject_candidate(arguments["candidate_id"])
            result = {"status": "rejected", "id": arguments["candidate_id"]}

        elif name == "memory_deprecate_entity":
            manager.deprecate_entity(
                entity_id=arguments["entity_id"],
                superseded_by=arguments.get("superseded_by")
            )
            result = {"status": "deprecated", "id": arguments["entity_id"]}

        elif name == "memory_get_pending":
            result = manager.get_pending_entities()

        elif name == "memory_recall":
            result = manager.recall(
                query=arguments["query"],
                top_k=arguments.get("top_k", 5),
                include_deprecated=arguments.get("include_deprecated", False)
            )

        elif name == "memory_search_by_type":
            result = manager.search_by_type(
                entity_type=arguments["entity_type"],
                query=arguments.get("query"),
                top_k=arguments.get("top_k", 10)
            )

        elif name == "memory_get_episode_detail":
            result = manager.get_episode_detail(arguments["episode_id"])

        elif name == "memory_stats":
            result = manager.get_stats()

        elif name == "memory_encoder_status":
            from .vector import is_encoder_ready, is_encoder_loading
            ready = is_encoder_ready()
            loading = is_encoder_loading()
            result = {
                "encoder_ready": ready,
                "encoder_loading": loading,
                "status": "ready" if ready else ("loading" if loading else "not_started"),
                "available_operations": {
                    "always_available": [
                        "memory_stats",
                        "memory_encoder_status",
                        "memory_get_current_episode",
                        "memory_get_pending",
                        "memory_start_episode",
                        "memory_close_episode",
                        "memory_add_entity",
                        "memory_confirm_entity",
                        "memory_reject_candidate",
                        "memory_deprecate_entity",
                        "memory_cache_message",
                        "memory_search_by_type (无 query 参数时)",
                        "memory_get_episode_detail",
                        "memory_list_episodes",
                        "memory_clear_cache",
                        "memory_cleanup_messages",
                    ],
                    "requires_encoder": [
                        "memory_recall",
                        "memory_search_by_type (有 query 参数时)",
                    ]
                },
                "_tip": "编码器首次加载通常需要 10-30 秒，之后会被缓存"
            }

        elif name == "memory_clear_cache":
            if not arguments.get("confirm", False):
                result = {"error": "必须设置 confirm=true 才能清空日志"}
            else:
                result = manager.clear_message_cache()

        elif name == "memory_cleanup_messages":
            days = arguments.get("days", 7)
            result = manager.cleanup_old_messages(days=days)

        elif name == "memory_list_episodes":
            result = manager.list_all_episodes(
                order=arguments.get("order", "desc"),
                limit=arguments.get("limit", 50)
            )

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2, default=str)
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"error": str(e)}, ensure_ascii=False)
        )]


# ==================== 资源定义 ====================

@server.list_resources()
async def list_resources() -> list[Resource]:
    """列出可用资源"""
    return [
        Resource(
            uri="memory://stats",
            name="Memory Stats",
            description="记忆系统统计信息",
            mimeType="application/json"
        ),
        Resource(
            uri="memory://current-episode",
            name="Current Episode",
            description="当前活跃的情景",
            mimeType="application/json"
        ),
        Resource(
            uri="memory://pending-entities",
            name="Pending Entities",
            description="待确认的实体候选",
            mimeType="application/json"
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """读取资源"""
    manager = get_manager()

    if uri == "memory://stats":
        return json.dumps(manager.get_stats(), ensure_ascii=False, indent=2)

    elif uri == "memory://current-episode":
        episode = manager.get_current_episode()
        return json.dumps(episode, ensure_ascii=False, indent=2, default=str)

    elif uri == "memory://pending-entities":
        pending = manager.get_pending_entities()
        return json.dumps(pending, ensure_ascii=False, indent=2, default=str)

    else:
        return json.dumps({"error": f"Unknown resource: {uri}"})


# ==================== 启动服务 ====================

def warmup_background():
    """
    后台预热：在独立进程中加载编码器，不阻塞主进程

    优化策略：使用 ProcessPoolExecutor 在子进程中加载模型，
    彻底避免 GIL 阻塞主线程

    注意：不再立即初始化 MemoryManager（会打开 ChromaDB），
    改为延迟初始化，避免与 hooks 争抢数据库锁。
    MemoryManager 会在第一次调用工具时通过 get_manager() 初始化。
    """
    import sys
    import time
    from pathlib import Path
    from datetime import datetime
    from .vector import start_encoder_warmup

    # 日志文件路径
    log_file = Path(os.environ.get('APPDATA', '')) / 'claude-memory' / 'warmup.log'

    def log(msg: str):
        """同时输出到 stderr 和文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line, file=sys.stderr)
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

    try:
        start = time.time()
        log("[memory-mcp] Warmup: initializing...")

        # 注意：不再立即初始化 MemoryManager，改为延迟初始化
        # 这样可以让 SessionStart hook 先完成，避免 ChromaDB 锁冲突
        log("[memory-mcp] MemoryManager will be initialized on first tool call (lazy init)")

        # 启动编码器预热（在独立进程中，不阻塞主进程）
        log("[memory-mcp] Starting encoder warmup (subprocess, won't block main process)...")
        start_encoder_warmup()

        log(f"[memory-mcp] Warmup initiated in {time.time()-start:.2f}s (encoder loading in background)")
    except Exception as e:
        log(f"[memory-mcp] Warmup error: {e}")


async def main():
    """主入口"""
    # 启动父进程监控（关键！防止成为僵尸进程）
    start_parent_monitor()

    try:
        # 后台预热：不阻塞服务启动，模型在后台线程加载
        warmup_background()

        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except Exception as e:
        print(f"[memory-mcp] Server error: {e}", file=sys.stderr)
    finally:
        print("[memory-mcp] Server shutting down.", file=sys.stderr)
        # 关闭编码器进程池，防止子进程变成孤儿进程
        try:
            from .vector import shutdown_encoder
            shutdown_encoder()
            print("[memory-mcp] Encoder pool shutdown complete.", file=sys.stderr)
        except Exception as e:
            print(f"[memory-mcp] Encoder shutdown error: {e}", file=sys.stderr)


def run():
    """同步启动入口"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
