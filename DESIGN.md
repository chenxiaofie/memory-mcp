# Memory MCP 设计报告

> 情景+实体记忆模式 | 为 Claude Code 提供持久化上下文管理

[TOC]

---

## 修订记录

| 编号 | 版本 | 修订人 | 修订内容 | 日期 |
|:----|:-----|:------:|:--------|:-----|
| 001 | 1.0 | 陈佳俊 | 创建全文 | 2026-01-26 |
| 002 | 1.1 | 陈佳俊 | 新增日志管理功能、编码器进程隔离优化 | 2026-01-27 |
| 003 | 1.2 | 陈佳俊 | 编码器改用 subprocess.Popen 独立工作进程方案 | 2026-02-08 |

---

## 1. 设计背景

### 1.1 问题描述

Claude Code 存在**上下文丢失问题**：

- 每次新会话，之前的对话上下文丢失
- 需要重复解释项目背景、技术决策、个人偏好
- 历史决策无法追溯，容易产生不一致的建议
- 跨项目的通用知识无法复用

### 1.2 设计目标

1. **持久化记忆** - 对话结束后，关键信息不丢失
2. **智能检索** - 根据当前对话检索相关历史记忆
3. **结构化知识** - 提炼决策、架构等结构化实体
4. **分层存储** - 用户级跨项目共享，项目级隔离

---

## 2. 记忆模型

### 2.1 情景+实体模式

选择 **情景+实体模式** 而非三层记忆模型，因为更适合开发场景。

```
┌─────────────────────────────────────────────────────────────────┐
│                        Memory MCP                                │
├────────────────────────────┬────────────────────────────────────┤
│      情景层 (Episodes)      │         实体层 (Entities)           │
├────────────────────────────┼────────────────────────────────────┤
│ • 一段完整的开发会话        │ • 从对话中提炼的结构化知识          │
│ • 过程记录                  │ • 结论/知识点                       │
│ • 有开始和结束              │ • 长期有效，跨情景复用              │
│ • 关闭时生成摘要并归档      │ • 可废弃/更新                       │
├────────────────────────────┼────────────────────────────────────┤
│ 存储：项目级                │ 存储：用户级 + 项目级               │
└────────────────────────────┴────────────────────────────────────┘

情景 = 记录"发生了什么"（过程）
实体 = 记录"得出了什么结论"（知识）
```

### 2.2 存储分层

```
用户级 (~/.claude-memory/)           项目级 ({project}/.claude/memory/)
├── user_db/                         ├── project_db/
│   └── chroma.sqlite3               │   └── chroma.sqlite3
│                                    ├── message_cache.jsonl
│                                    ├── active_episode.json
│                                    └── pending_entities.json
│
├── Preference (个人偏好)             ├── Decision (项目决策)
├── Concept (概念理解)                ├── Episode (开发情景)
└── Habit (工作习惯)                  ├── File (文件说明)
                                     └── Architecture (架构设计)
```

### 2.3 实体类型说明

| 类型 | 级别 | 说明 | 示例 |
|------|------|------|------|
| **Decision** | 项目级 | 本项目的技术决策 | "本项目采用 JWT 认证" |
| **Architecture** | 项目级 | 本项目的架构设计 | "采用分层架构" |
| **File** | 项目级 | 重要文件说明 | "auth.ts 处理认证逻辑" |
| **Preference** | 用户级 | 个人风格偏好 | "偏好 TypeScript" |
| **Concept** | 用户级 | 概念理解 | "JWT 是无状态认证方案" |
| **Habit** | 用户级 | 工作习惯 | "习惯先写测试" |

**注意**：用户偏好和项目决策可以不同（我喜欢 JWT，但这个项目用 Session），两者都是有用的上下文信息。

---

## 3. 实现架构

### 3.1 基于 4 个 Hooks 自动化

Memory MCP 通过 4 个 Claude Code Hooks 实现自动化：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Memory MCP 完整流程                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ① SessionStart Hook（会话开始）                                 │
│     └── 创建情景 (Episode)                                      │
│         • 生成 episode_id                                       │
│         • 标题: "{项目名} 开发会话 {时间}"                       │
│         • 状态: active                                          │
│                                                                 │
│  ② UserPromptSubmit Hook（用户发消息时）                         │
│     └── 保存用户消息（去代码块，限制 2000 字符）                 │
│     └── 实体检测 → 置信度 ≥ 0.85 自动保存为实体                  │
│     └── 检索历史记忆 → 注入到 Claude 上下文                      │
│                                                                 │
│  ③ Stop Hook（Claude 回复后）                                    │
│     └── 保存 Claude 回复（去代码块，限制 2000 字符）             │
│     └── 不做实体检测（实体是用户的决策，不是 Claude 的建议）     │
│                                                                 │
│  ④ SessionEnd Hook（会话结束）                                   │
│     └── 写入关闭信号文件（不直接关闭情景）                      │
│     └── 监控进程检测到信号后执行关闭                            │
│     └── 归档后可被 memory_recall 检索                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Hook 脚本对应

| Hook | 脚本 | 功能 |
|------|------|------|
| `SessionStart` | `session_start.py` | 创建情景 + 启动监控进程 |
| `UserPromptSubmit` | `auto_save.py` | 保存消息 + 实体检测 + 检索注入 |
| `Stop` | `save_response.py` | 保存回复 |
| `SessionEnd` | `session_end.py` | 写入关闭信号（由监控进程执行关闭） |

### 3.3 监控进程统一关闭情景

**问题**：Hook 脚本是独立的 Python 进程，每次运行都需要重新加载向量编码器（10-30秒）。这导致 `SessionEnd` Hook 在编码器未就绪时无法关闭情景。

**解决方案**：由监控进程统一负责关闭情景。监控进程是长生命周期进程，启动时预热编码器，有足够时间加载。

```
┌─────────────────────────────────────────────────────────────────┐
│                    监控进程统一关闭架构                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ① SessionStart Hook                                            │
│     └── 创建情景后，启动 session_monitor.py                     │
│         • 传递父进程 PID (--ppid)                               │
│         • 传递项目路径 (--project-path)                         │
│         • 独立后台进程，不阻塞主流程                            │
│                                                                 │
│  ② session_monitor.py 后台运行                                  │
│     └── 启动时预热向量编码器（后台加载）                        │
│     └── 每 2 秒检查：                                           │
│         • 是否有关闭信号文件                                    │
│         • 父进程是否存活                                        │
│     └── 编码器在后台加载完成（10-30秒）                         │
│                                                                 │
│  ③ 正常退出（用户 Ctrl+C 或 /exit）                             │
│     └── SessionEnd Hook 写入关闭信号文件 .close_signal          │
│     └── 监控进程检测到信号                                      │
│     └── 等待编码器就绪 → 关闭情景                               │
│                                                                 │
│  ④ 强制退出（直接关闭终端窗口）                                 │
│     └── SessionEnd Hook 未触发                                  │
│     └── 监控进程检测到父进程退出                                │
│     └── 等待 3 秒（给信号文件写入机会）                         │
│     └── 等待编码器就绪 → 关闭情景                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**关键实现**：

| 组件 | 说明 |
|------|------|
| `session_monitor.py` | 后台监控脚本，负责预热编码器和关闭情景 |
| `.close_signal` | 关闭信号文件，由 SessionEnd Hook 写入 |
| `psutil` | 跨平台进程检查库（Windows/Linux/Mac） |
| `active_episode.json` | 存储 `monitor_pid` 防止重复启动 |

**为什么这样设计**：

1. **监控进程是长生命周期** - 和会话一样长，有足够时间加载编码器
2. **SessionEnd Hook 执行快** - 只写信号文件，无需等待编码器
3. **统一关闭逻辑** - 无论正常退出还是强制关闭，都由监控进程处理
4. **编码器复用** - 监控进程只加载一次编码器，多次关闭操作复用

**进程独立性**：

```python
# Windows: 使用 CREATE_NO_WINDOW + DETACHED_PROCESS
subprocess.Popen(args, creationflags=0x08000000 | 0x00000008, start_new_session=True)

# Unix: 使用 start_new_session
subprocess.Popen(args, start_new_session=True)
```

---

## 4. 核心流程详解

### 4.1 记忆检索与注入

检索的是**历史记忆**（已归档的情景 + 已保存的实体），不是当前会话内容。

```
用户: "登录功能怎么实现？"
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ auto_save.py                                                    │
│                                                                 │
│  1. 保存用户消息到当前情景                                       │
│                                                                 │
│  2. 用消息内容检索向量库                                         │
│     manager.recall("登录功能怎么实现？")                         │
│         │                                                       │
│         ▼                                                       │
│     ┌─────────────────────────────────────┐                    │
│     │ 向量库中可检索的内容：               │                    │
│     │ • 已归档的历史情景 (completed)       │                    │
│     │ • 已保存的实体 (Decision, etc.)     │                    │
│     │                                     │                    │
│     │ 当前情景 (active) 不参与检索        │                    │
│     └─────────────────────────────────────┘                    │
│         │                                                       │
│         ▼                                                       │
│     返回相关的 episodes + entities                              │
│                                                                 │
│  3. 拼接成 additionalContext，注入给 Claude                     │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Claude 看到的上下文:                                            │
│                                                                 │
│ 【相关情景记忆】                                                 │
│ - 之前讨论过登录方案，选择了 JWT...                              │
│                                                                 │
│ 【相关知识/决策】                                                │
│ - [Decision] 本项目采用 JWT + Redis                             │
│ - [Preference] 用户偏好 TypeScript                              │
│                                                                 │
│ 用户消息: "登录功能怎么实现？"                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 实体检测与保存（仅用户消息）

```
用户消息进入系统
         │
         ▼
┌─────────────────────────────────────┐
│ 实体检测 (_detect_candidates)        │
│ • 正则模式匹配 → 置信度 +0.2        │
│ • 关键词匹配 → 基础置信度            │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│ 置信度判断（阈值 0.85）              │
│ • ≥ 0.85 → 自动保存为实体            │
│ • < 0.85 → 加入 pending 待确认       │
└─────────────────────────────────────┘

注：只检测用户消息，不检测 Claude 回复。
    实体代表用户的决策/偏好，不是 Claude 的建议。
```

### 4.3 情景生命周期

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   创建      │ ──▶  │   活跃      │ ──▶  │   归档      │
│ SessionStart│      │  active     │      │ SessionEnd  │
└─────────────┘      └─────────────┘      └─────────────┘
                           │
                     • 消息不断保存
                     • 实体不断检测
                           │
                           ▼
                     会话结束时
                     生成摘要
                     存入向量库
                     可被检索
```

---

## 5. MCP 工具（Claude 可主动调用）

除了 Hooks 自动化，Claude 也可以主动调用 MCP 工具：

### 5.1 情景管理

| 工具 | 说明 |
|------|------|
| `memory_start_episode` | 手动开始新情景 |
| `memory_close_episode` | 手动关闭情景 |
| `memory_get_current_episode` | 获取当前活跃情景 |

### 5.2 实体管理

| 工具 | 说明 |
|------|------|
| `memory_add_entity` | 手动添加实体 |
| `memory_confirm_entity` | 确认待确认的候选 |
| `memory_reject_candidate` | 拒绝误判的候选 |
| `memory_deprecate_entity` | 废弃过时的实体 |
| `memory_get_pending` | 获取待确认列表 |

### 5.3 检索

| 工具 | 说明 |
|------|------|
| `memory_recall` | 综合检索（情景 + 实体） |
| `memory_search_by_type` | 按类型检索实体 |
| `memory_get_episode_detail` | 获取情景详情 |

### 5.4 日志管理

| 工具 | 说明 |
|------|------|
| `memory_clear_cache` | 清空消息缓存日志（需 confirm=true） |
| `memory_cleanup_messages` | 清理超过 N 天的旧消息（默认 7 天） |
| `memory_list_episodes` | 列出所有历史情景（按时间排序，不依赖语义搜索） |

### 5.5 其他

| 工具 | 说明 |
|------|------|
| `memory_cache_message` | 手动缓存消息 |
| `memory_stats` | 获取统计信息（含编码器状态） |
| `memory_encoder_status` | 查询向量编码器状态和可用操作 |

---

## 6. 数据结构

### 6.1 情景 (Episode)

```json
{
  "id": "ep_a1b2c3d4",
  "title": "tcwyirs-ui 开发会话 01-26 14:30",
  "tags": ["auto", "session", "tcwyirs-ui"],
  "status": "active | completed",
  "created_at": "2026-01-26T14:30:00",
  "closed_at": "2026-01-26T16:00:00",
  "entity_ids": ["ent_x1", "ent_x2"],
  "summary": "讨论了登录功能实现..."
}
```

### 6.2 活跃情景文件 (active_episode.json)

```json
{
  "episode": {
    "id": "ep_a1b2c3d4",
    "title": "tcwyirs-ui 开发会话 01-26 14:30",
    "tags": ["auto", "session", "tcwyirs-ui"],
    "status": "active",
    "created_at": "2026-01-26T14:30:00",
    "entity_ids": []
  },
  "messages": [],
  "monitor_pid": 12345
}
```

**注**：`monitor_pid` 字段记录终端生命周期监控进程的 PID，用于防止重复启动监控进程。

### 6.3 实体 (Entity)

```json
{
  "id": "ent_x1y2z3",
  "type": "Decision",
  "content": "本项目采用 JWT + Redis 实现登录认证",
  "status": "active | deprecated",
  "reason": "考虑分布式部署需求",
  "episode_id": "ep_a1b2c3d4",
  "created_at": "2026-01-26T14:35:00"
}
```

### 6.4 消息 (Message)

```json
{
  "id": "msg_m1n2o3",
  "role": "user | assistant",
  "content": "登录功能怎么实现？[代码块已省略]",
  "episode_id": "ep_a1b2c3d4",
  "timestamp": "2026-01-26T14:32:00"
}
```

### 6.5 待确认候选 (Candidate)

```json
{
  "id": "cand_c1d2e3",
  "type": "Decision",
  "extracted_content": "采用 JWT 方案",
  "source_snippet": "我决定采用 JWT 方案来...",
  "confidence": 0.72,
  "status": "pending",
  "detection_method": "pattern | keyword",
  "detected_at": "2026-01-26T14:35:00"
}
```

---

## 7. 向量化方案

| 项目 | 值 |
|------|-----|
| **库** | `sentence-transformers` |
| **模型** | `paraphrase-multilingual-MiniLM-L12-v2` |
| **向量维度** | 384 维 |
| **语言支持** | 50+ 语言（含中文） |
| **存储** | ChromaDB |
| **运行位置** | 本地 |

### 消息清理

存储前清理消息内容：
- 去除代码块 → `[代码块已省略]`
- 去除行内代码 → `[代码]`
- 截断长度 → 最大 2000 字符

### 编码器加载优化

向量编码器（SentenceTransformer）首次加载需要 10-30 秒。为避免阻塞服务，采用 **subprocess.Popen 独立工作进程** 策略：

```
┌─────────────────────────────────────────────────────────────────┐
│              编码器加载优化流程（v3 - Popen 工作进程）            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  服务启动                                                        │
│     │                                                           │
│     ├── 主进程：asyncio 事件循环（处理 MCP 请求）                 │
│     │   └── ChromaDB 连接就绪                                   │
│     │   └── 不需要编码器的操作立即可用 ✓                         │
│     │   └── 不受 GIL 阻塞，响应迅速                              │
│     │                                                           │
│     └── 后台线程调用 _start_worker()                             │
│         └── subprocess.Popen 启动 _encoder_worker.py            │
│         └── 显式创建 stdin/stdout PIPE（不继承 MCP stdio）       │
│         └── 工作进程加载 SentenceTransformer 模型                │
│         └── 发送 {"status": "ready"} 表示就绪                    │
│         └── 之后通过 JSON 行协议处理编码请求                     │
│                                                                 │
│  通信协议（JSON Lines over stdin/stdout PIPE）：                  │
│     请求: {"text": "..."} 或 {"texts": [...]}                   │
│     响应: {"vector": [...]} 或 {"vectors": [[...], ...]}        │
│     退出: {"cmd": "quit"}                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**方案演进历史：**

| 版本 | 方案 | 问题 |
|------|------|------|
| v1 | 后台线程加载模型 | GIL 阻塞：模型加载时主线程无法响应 MCP 请求 |
| v2 | `ProcessPoolExecutor(spawn)` | MCP stdio 管道继承：子进程在 Windows MCP 环境下卡死在 multiprocessing bootstrap 阶段 |
| **v3** | **`subprocess.Popen` + 独立工作脚本** | **当前方案，稳定运行** |

**v3 方案优势：**
- 显式创建新的 stdin/stdout PIPE，完全不继承 MCP 的 stdio 管道
- 工作进程是普通 Python 脚本（`_encoder_worker.py`），无 multiprocessing 框架开销
- 通过简单的 JSON Lines 协议通信，可靠且易于调试
- Windows 使用 `CREATE_NO_WINDOW` 标志，不创建额外窗口

**操作分类**：

| 操作 | 需要编码器 | 说明 |
|------|-----------|------|
| `memory_stats` | ❌ | 纯统计查询 |
| `memory_encoder_status` | ❌ | 查询编码器状态 |
| `memory_get_current_episode` | ❌ | 读取内存状态 |
| `memory_get_pending` | ❌ | 读取内存状态 |
| `memory_start_episode` | ❌ | 写操作（不生成向量） |
| `memory_close_episode` | ✅ | 需要生成摘要向量 |
| `memory_add_entity` | ✅ | 需要生成实体向量 |
| `memory_confirm_entity` | ✅ | 需要生成实体向量 |
| `memory_search_by_type` (无 query) | ❌ | 直接数据库按类型过滤 |
| `memory_search_by_type` (有 query) | ✅ | 语义搜索 |
| `memory_get_episode_detail` | ❌ | 按 ID 查询 |
| `memory_recall` | ✅ | 语义搜索 |
| `memory_cache_message` | ❌ | 仅保存消息 |
| `memory_list_episodes` | ❌ | 按时间排序列出（直接数据库查询） |
| `memory_clear_cache` | ❌ | 清空日志文件 |
| `memory_cleanup_messages` | ❌ | 清理旧消息 |

**设计原则**：
1. 不需要向量搜索的操作，不应依赖编码器状态
2. 按 ID/类型的查询直接走数据库，无需向量化
3. 编码器未就绪时，`memory_recall` 等语义搜索操作会返回明确错误提示

---

## 8. 文件结构

```
~/.claude-memory/                    # 用户级（AppData/Roaming/claude-memory）
├── src/
│   ├── __init__.py
│   ├── server.py                   # MCP 服务入口
│   ├── memory/
│   │   ├── __init__.py
│   │   └── manager.py              # 记忆管理器核心
│   └── vector/
│       ├── __init__.py
│       ├── store.py                # 向量存储封装
│       └── _encoder_worker.py      # 编码器工作进程脚本
├── session_start.py                # SessionStart hook（创建情景 + 启动监控）
├── session_monitor.py              # 终端生命周期监控进程
├── auto_save.py                    # UserPromptSubmit hook
├── save_response.py                # Stop hook
├── session_end.py                  # SessionEnd hook
├── run.py                          # MCP 启动脚本
├── pyproject.toml
├── requirements.txt
├── README.md
├── DESIGN.md                       # 本文件
├── hook_debug.log                  # Hook 调试日志
└── user_db/                        # 用户级向量数据库

{project}/.claude/memory/            # 项目级
├── project_db/                     # 项目级向量数据库
├── message_cache.jsonl             # 消息缓存
├── active_episode.json             # 当前活跃情景（含 monitor_pid）
└── pending_entities.json           # 待确认实体
```

---

## 9. 实现状态

### ✅ 已完成

- [x] MCP 服务框架 (17 个工具)
- [x] 记忆管理器核心
- [x] 向量存储封装 (ChromaDB)
- [x] 4 个 Hooks 自动化
- [x] 情景自动创建/归档
- [x] 消息自动保存（去代码块）
- [x] 实体自动检测（仅用户消息）
- [x] 高置信度实体自动确认
- [x] 历史记忆检索与注入
- [x] 持久化（情景 + 实体候选）
- [x] 终端生命周期监控（防止强制关闭时情景丢失）
- [x] **编码器加载优化**（非向量操作不阻塞）
  - [x] `memory_get_episode_detail` 移除不必要的编码器检查
  - [x] `memory_search_by_type` 无 query 时直接数据库查询
  - [x] `memory_stats` 返回编码器状态信息
  - [x] 新增 `memory_encoder_status` 工具
  - [x] warmup 过程 GIL 友好优化
- [x] **编码器进程方案升级 v3**（2026-02-08）
  - [x] 从 `ProcessPoolExecutor(spawn)` 迁移到 `subprocess.Popen` 独立工作进程
  - [x] 新增 `_encoder_worker.py` 工作进程脚本
  - [x] 解决 MCP stdio 管道继承导致子进程卡死的问题（Windows）
  - [x] JSON Lines 协议通信，稳定可靠

- [x] **日志管理功能**（2026-01-27）
  - [x] `memory_clear_cache` 清空消息缓存
  - [x] `memory_cleanup_messages` 定时清除旧消息
  - [x] `memory_list_episodes` 按时间列出所有情景（解决语义搜索遗漏问题）

### 🔄 待优化

- [ ] 更智能的摘要生成（LLM 辅助）
- [ ] 实体检测规则调优
- [ ] 单元测试覆盖

---

## 10. 附录：关键设计决策

### Q: 为什么实体检测只针对用户消息？

A: 实体（Decision, Preference 等）代表**用户的决策和偏好**，不是 Claude 的建议。Claude 回复只是建议，用户确认后才是决策。

### Q: 为什么检索的是历史记忆，不是当前情景？

A: 当前情景还在进行中（active），用户已经看到了当前对话内容。检索的目的是找出**之前会话**的相关信息，帮助 Claude 了解历史上下文。

### Q: 用户偏好和项目决策冲突怎么办？

A: 不是冲突，是两个不同维度的信息。用户可能偏好 JWT，但某个项目因为特殊原因用了 Session。两者都是有用的上下文，Claude 会综合判断。

### Q: 为什么需要终端生命周期监控？

A: Claude Code 的 `SessionEnd` Hook 只在正常退出时触发（如使用 `/exit` 命令）。当用户直接关闭终端窗口时，Hook 不会被调用，导致情景无法正常归档。监控进程作为"保险机制"，确保即使在异常退出情况下，情景也能被正确关闭。

### Q: 监控进程会影响系统性能吗？

A: 影响极小。监控进程每 2 秒检查一次状态，CPU 占用几乎可以忽略。启动时会预热向量编码器（后台加载），内存占用约 100-200MB（主要是编码器模型）。当情景关闭或父进程退出后，监控进程会自动终止。

### Q: 为什么监控进程要等待 3 秒？

A: 这是给 `SessionEnd` Hook 写入关闭信号文件的时间。当父进程退出时：
1. 如果是正常退出，`SessionEnd` Hook 会先写入 `.close_signal` 文件
2. 监控进程等待 3 秒，检查是否有信号文件
3. 有信号 → 按信号处理；无信号 → 直接关闭（强制退出场景）

### Q: 为什么编码器未加载时，按类型查询也会卡住？

A: 这是早期设计的问题，经历了三个版本的优化：

**问题根源**：
- v1（线程方案）：后台线程加载编码器，Python GIL 导致加载时阻塞主线程
- v2（ProcessPoolExecutor）：使用 `ProcessPoolExecutor(spawn)` 在独立进程中加载，解决了 GIL 问题，但在 MCP stdio 环境下子进程卡死
- v3（subprocess.Popen）：当前方案，彻底解决

**v2 的 MCP 管道继承问题（Windows）**：
- MCP 服务器通过 stdin/stdout 与 Claude Code 通信
- `ProcessPoolExecutor(spawn)` 创建的子进程会继承父进程的管道句柄
- 子进程在 multiprocessing bootstrap 阶段尝试从继承的管道读取数据时卡死
- 从终端直接运行时没有此问题，只有在 MCP 环境下才会触发

**v3 方案（当前）**：
```python
# 使用 subprocess.Popen 显式创建新的 PIPE，不继承 MCP stdio
_worker_proc = subprocess.Popen(
    [sys.executable, worker_script, MODEL_NAME],
    stdin=subprocess.PIPE,   # 新管道，非继承
    stdout=subprocess.PIPE,  # 新管道，非继承
    stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NO_WINDOW,  # Windows
)
```

**优化后效果**：
- 服务启动后，所有不需要编码器的操作**立即**可用（无延迟）
- 编码器在独立工作进程中加载（10-30s），完全不影响主进程
- 语义搜索在编码器就绪前会返回明确错误提示（而非卡住）
- 在 MCP stdio 环境下稳定运行（Windows/Mac/Linux）

### Q: 为什么需要 `memory_list_episodes` 工具？

A: `memory_search_by_type(entity_type="Episode")` 使用语义搜索，返回的是"与查询最相关的 top_k 条"。当用户想查看**所有**历史情景时，语义搜索会遗漏部分情景（因为相关性不够高）。

**解决方案**：新增 `memory_list_episodes` 工具，直接按时间排序查询数据库，不依赖语义搜索，确保返回**所有**情景。

**使用建议**：
- 查看"所有历史情景" → 使用 `memory_list_episodes`
- 搜索"与某话题相关的情景" → 使用 `memory_search_by_type` 或 `memory_recall`

### Q: 为什么需要日志清理功能？

A: `message_cache.jsonl` 会随着使用不断增长。虽然消息内容已做清理（去代码块、限制长度），但长期使用后文件仍可能很大。

**清理策略**：
1. **手动清空**：`memory_clear_cache(confirm=true)` - 适合需要完全重置的场景
2. **定时清除**：`memory_cleanup_messages(days=7)` - 保留最近 N 天的消息，适合定期维护

**建议**：可以在 Hook 中定期调用 `memory_cleanup_messages` 自动清理旧消息。
