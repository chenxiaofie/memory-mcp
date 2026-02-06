# Memory MCP Service

[English](README.md) | [中文](README_zh.md)

情景+实体记忆 MCP 服务，为 Claude Code 提供持久化记忆能力。

## 特性

- **情景记忆 (Episodes)**: 按任务/功能划分的对话场景
- **实体记忆 (Entities)**: 结构化的知识单元（决策、概念、偏好等）
- **双层存储**: 用户级（跨项目）+ 项目级（项目隔离）
- **实时缓存**: 消息实时存储，防止丢失
- **语义检索**: 基于向量的语义搜索

## 安装

### Windows 一键安装

直接运行项目根目录的 `install.bat` 文件：

```bash
# 双击运行或命令行执行
install.bat
```

### Mac/Linux 一键安装

直接运行项目根目录的 `install.sh` 文件：

```bash
# 命令行执行
chmod +x install.sh
./install.sh
```

### 手动安装

```bash
cd .claude/memory-mcp

# 创建虚拟环境
python -m venv venv310

# 激活虚拟环境
# Windows:
venv310\Scripts\activate
# Mac/Linux:
source venv310/bin/activate

# 安装依赖
pip install -e .
```

## 配置 Claude Code

### 1. MCP 服务配置

#### 方法 1：使用命令行添加（推荐）

```bash
claude mcp add memory-mcp -- python -m src.server
```

#### 方法 2：手动配置 settings.json

编辑 `~/.claude/settings.json`（全局配置）：

```json
{
  "mcpServers": {
    "memory-mcp": {
      "command": "/path/to/your/venv/bin/python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/your/memory-mcp",
      "env": {
        "CLAUDE_PROJECT_ROOT": "/path/to/your/project"
      }
    }
  },
  "hooks": {
    "SessionStart": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/your/venv/bin/python",
            "args": ["/path/to/your/memory-mcp/session_start.py"],
            "env": {}
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/your/venv/bin/python",
            "args": ["/path/to/your/memory-mcp/auto_save.py"],
            "env": {}
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/your/venv/bin/python",
            "args": ["/path/to/your/memory-mcp/save_response.py"],
            "env": {}
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/your/venv/bin/python",
            "args": ["/path/to/your/memory-mcp/session_end.py"],
            "env": {}
          }
        ]
      }
    ]
  }
}
```

### 2. Hooks 功能说明

项目提供 4 个自动化 hooks 实现完整的会话生命周期管理：

| Hook 名称          | 文件                     | 功能描述                                                                 |
|-------------------|--------------------------|--------------------------------------------------------------------------|
| SessionStart      | `session_start.py`       | 会话开始时自动创建情景，启动终端生命周期监控                             |
| UserPromptSubmit  | `auto_save.py`           | 用户提交 prompt 时自动保存消息到记忆系统                                 |
| Stop              | `save_response.py`       | 会话停止时保存助手回复到记忆系统                                         |
| SessionEnd        | `session_end.py`         | 会话结束时发送关闭信号给监控进程，由监控进程负责关闭情景并生成摘要         |

### 3. 验证配置

```bash
# 检查 MCP 服务器状态
claude mcp list

# 预期输出
Checking MCP server health...
playwright: npx @playwright/mcp@latest - ✓ Connected
memory-mcp: /path/to/your/venv/bin/python -m src.server - ✓ Connected
```

## 工具列表

### 消息缓存

- `memory_cache_message`: 缓存消息

### 情景管理

- `memory_start_episode`: 开始新情景
- `memory_close_episode`: 关闭情景
- `memory_get_current_episode`: 获取当前情景

### 实体管理

- `memory_add_entity`: 添加实体
- `memory_confirm_entity`: 确认候选实体
- `memory_reject_candidate`: 拒绝候选
- `memory_deprecate_entity`: 废弃实体
- `memory_get_pending`: 获取待确认实体

### 检索

- `memory_recall`: 综合检索
- `memory_search_by_type`: 按类型检索
- `memory_get_episode_detail`: 获取情景详情

### 统计

- `memory_stats`: 获取统计信息

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

- 用户级: `~/.claude-memory/` (Windows: `%APPDATA%/claude-memory/`)
- 项目级: `{project}/.claude/memory/`

## 示例使用

```
# 开始新任务
Claude 调用: memory_start_episode("登录功能开发", ["auth"])

# 记录决策
Claude 调用: memory_add_entity("Decision", "采用 JWT + Redis 方案", "考虑分布式部署")

# 检索历史
Claude 调用: memory_recall("登录方案")

# 关闭任务
Claude 调用: memory_close_episode("完成了 JWT 登录功能的开发")
```

## 许可证

MIT License - 详见 LICENSE 文件。
