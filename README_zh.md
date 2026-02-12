# Memory MCP Service

[![PyPI version](https://img.shields.io/pypi/v/chenxiaofie-memory-mcp)](https://pypi.org/project/chenxiaofie-memory-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/chenxiaofie-memory-mcp)](https://pypi.org/project/chenxiaofie-memory-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[English](README.md) | [中文](README_zh.md)

情景+实体记忆 MCP 服务，为 Claude Code 提供持久化记忆能力。

## 特性

- **情景记忆 (Episodes)**: 按任务/功能划分的对话场景
- **实体记忆 (Entities)**: 结构化的知识单元（决策、概念、偏好等）
- **双层存储**: 用户级（跨项目共享）+ 项目级（项目隔离）
- **实时缓存**: 消息实时存储，防止丢失
- **语义检索**: 基于向量的语义搜索

## 安装

### Windows 一键安装

双击运行项目根目录的 `install.bat`：

```bash
install.bat
```

### Mac/Linux 一键安装

```bash
chmod +x install.sh
./install.sh
```

> 安装脚本会自动创建 Python 3.10 虚拟环境（`venv310`）并安装依赖。

## 配置 Claude Code

### 重要提示

本包依赖 chromadb，其使用的 Pydantic V1 **不支持 Python 3.14+**。

**必须使用：本地源码 + `venv310` 虚拟环境（Python 3.10）。**

### 添加 MCP 服务

```bash
# Windows:
claude mcp add memory-mcp -s user -- "C:\path\to\memory-mcp\venv310\Scripts\python.exe" -m src.server

# Mac/Linux:
claude mcp add memory-mcp -s user -- /path/to/memory-mcp/venv310/bin/python -m src.server
```

#### 手动编辑配置文件

编辑 `~/.claude/settings.json`，添加：

```json
{
  "mcpServers": {
    "memory-mcp": {
      "command": "C:\\path\\to\\memory-mcp\\venv310\\Scripts\\python.exe",
      "args": ["-m", "src.server"],
      "cwd": "C:\\path\\to\\memory-mcp"
    }
  }
}
```

### 配置 Hooks（可选）

> **重要：** Hooks **仅在使用本地源码安装时可用**。

Hooks 可实现自动消息保存，配置后会话无需手动调用记忆工具。

在 `~/.claude/settings.json` 中添加 `hooks` 配置：

**Mac/Linux:**
```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "/path/to/venv310/bin/python",
        "args": ["/path/to/memory-mcp/session_start.py"]
      }]
    }],
    "UserPromptSubmit": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "/path/to/venv310/bin/python",
        "args": ["/path/to/memory-mcp/auto_save.py"]
      }]
    }],
    "Stop": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "/path/to/venv310/bin/python",
        "args": ["/path/to/memory-mcp/save_response.py"]
      }]
    }],
    "SessionEnd": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "/path/to/venv310/bin/python",
        "args": ["/path/to/memory-mcp/session_end.py"]
      }]
    }]
  }
}
```

**Windows（需要 cmd 包装器）：**
```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "cmd",
        "args": ["/c", "C:\\path\\to\\memory-mcp\\venv310\\Scripts\\python.exe", "C:\\path\\to\\memory-mcp\\session_start.py"]
      }]
    }],
    "UserPromptSubmit": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "cmd",
        "args": ["/c", "C:\\path\\to\\memory-mcp\\venv310\\Scripts\\python.exe", "C:\\path\\to\\memory-mcp\\auto_save.py"]
      }]
    }],
    "Stop": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "cmd",
        "args": ["/c", "C:\\path\\to\\memory-mcp\\venv310\\Scripts\\python.exe", "C:\\path\\to\\memory-mcp\\save_response.py"]
      }]
    }],
    "SessionEnd": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "cmd",
        "args": ["/c", "C:\\path\\to\\memory-mcp\\venv310\\Scripts\\python.exe", "C:\\path\\to\\memory-mcp\\session_end.py"]
      }]
    }]
  }
}
```

**Hooks 说明：**

| Hook 名称         | 作用                      | 耗时 |
|-----------------|---------------------------|------|
| SessionStart     | 创建情景（轻量 JSON 操作，不导入 chromadb） | ~50ms |
| UserPromptSubmit | 保存消息 + 实体检测 + 记忆检索注入 | ~1-2s |
| Stop            | 保存助手的回复              | ~1s |
| SessionEnd       | 写入关闭信号 + 移除项目信任状态（不导入 chromadb） | ~50ms |

> **说明：** SessionStart 和 SessionEnd Hook 采用轻量化设计，不导入 MemoryManager/chromadb，避免重型依赖初始化（10-30秒）导致 hook 超时。情景的关闭归档由后台监控进程负责。

### 验证配置

```bash
claude mcp list
```

预期输出应显示 `memory-mcp: ... - ✓ Connected`

## 使用方式

### 自动模式（启用 Hooks 后）

配置 Hooks 后，对话会自动保存，无需手动操作。

### 手动模式

手动调用记忆工具：

```
# 开始新情景
memory_start("登录功能开发", ["auth"])

# 记录决策
memory_add_entity("Decision", "采用 JWT + Redis 方案", "考虑分布式部署")

# 检索历史
memory_recall("登录方案")

# 关闭情景
memory_close_episode("完成登录功能开发")
```

## 工具列表

- `memory_start_episode`: 开始新情景
- `memory_close_episode`: 关闭情景
- `memory_get_current_episode`: 获取当前情景
- `memory_add_entity`: 添加实体
- `memory_confirm_entity`: 确认候选实体
- `memory_reject_candidate`: 拒绝候选
- `memory_deprecate_entity`: 废弃实体
- `memory_get_pending`: 获取待确认实体
- `memory_recall`: 综合检索
- `memory_search_by_type`: 按类型检索
- `memory_get_episode_detail`: 获取情景详情
- `memory_list_episodes`: 按时间列出所有情景
- `memory_stats`: 获取统计信息
- `memory_encoder_status`: 查询编码器状态
- `memory_cache_message`: 手动缓存消息
- `memory_clear_cache`: 清空消息缓存
- `memory_cleanup_messages`: 清理旧消息

## 实体类型

### 用户级（跨项目共享）

- `Preference`: 用户偏好
- `Concept`: 通用概念
- `Habit`: 工作习惯

### 项目级（项目隔离）

- `Decision`: 项目决策
- `Episode`: 开发情景
- `File`: 文件说明
- `Architecture`: 架构设计

## 存储位置

- **用户级**: `~/.claude-memory/` (Windows: `%APPDATA%/claude-memory/`)
- **项目级**: `{项目根目录}/.claude/memory/`

## 许可证

MIT License
