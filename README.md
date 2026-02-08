# Memory MCP Service

[English](README.md) | [中文](README_zh.md)

A scenario + entity memory MCP service that provides persistent memory capabilities for Claude Code.

## Features

- **Episodes**: Dialogue scenes divided by task/function
- **Entities**: Structured knowledge units (decisions, concepts, preferences, etc.)
- **Dual-layer storage**: User-level (cross-project) + Project-level (project isolated)
- **Real-time cache**: Messages are stored in real-time to prevent loss
- **Semantic retrieval**: Vector-based semantic search

## Installation

### Windows One-click Installation

Run `install.bat` file in the project root directory:

```bash
install.bat
```

### Mac/Linux One-click Installation

```bash
chmod +x install.sh
./install.sh
```

> The installation script will automatically create a Python 3.10 virtual environment (`venv310`) and install dependencies.

## Configure Claude Code

### Important

This package depends on chromadb which uses Pydantic V1, **not compatible with Python 3.14+**.

**Required: Use local source code with `venv310` virtual environment (Python 3.10).**

### Add MCP Server

```bash
# Windows:
claude mcp add memory-mcp -s user -- "C:\path\to\memory-mcp\venv310\Scripts\python.exe" -m src.server

# Mac/Linux:
claude mcp add memory-mcp -s user -- /path/to/memory-mcp/venv310/bin/python -m src.server
```

#### Manual Configuration File

Edit `~/.claude/settings.json` and add:

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

### Configure Hooks (Optional)

> **Important:** Hooks are **only available with local source code installation**.

Hooks enable automatic message saving. Once configured, conversations will be saved without manual memory tool calls.

Add to following `hooks` configuration to `~/.claude/settings.json`:

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

**Windows (requires cmd wrapper):**
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

**Hooks Description:**

| Hook Name       | Purpose                            |
|----------------|------------------------------------|
| SessionStart   | Create new episode when session starts |
| UserPromptSubmit | Save user-submitted messages       |
| Stop           | Save assistant responses             |
| SessionEnd     | Close episode and generate summary   |

### Verify Configuration

```bash
claude mcp list
```

Expected output should show `memory-m-mcp: ... - ✓ Connected`

## Usage

### Automatic Mode (With Hooks)

After configuring hooks, conversations are automatically saved without manual operation.

### Manual Mode

Manually call memory tools:

```
# Start a new task
memory_start("Login Function Development", ["auth"])

# Record a decision
memory_add_entity("Decision", "Adopt JWT + Redis solution", "Consider distributed deployment")

# Retrieve history
memory_recall("Login scheme")

# Close task
memory_close_episode("Completed JWT login function development")
```

## Tools List

- `memory_start_episode`: Start a new episode
- `memory_close_episode`: Close an episode
- `memory_get_current_episode`: Get current episode
- `memory_add_entity`: Add entity
- `memory_confirm_entity`: Confirm candidate entity
- `memory_reject_candidate`: Reject candidate
- `memory_deprecate_entity`: Deprecate entity
- `memory_get_pending`: Get pending entities
- `memory_recall`: Comprehensive retrieval
- `memory_search_by_type`: Search by type
- `memory_get_episode_detail`: Get episode detail
- `memory_list_episodes`: List all episodes by time
- `memory_stats`: Get statistics
- `memory_encoder_status`: Check encoder status
- `memory_cache_message`: Manually cache a message
- `memory_clear_cache`: Clear message cache
- `memory_cleanup_messages`: Clean up old messages

## Entity Types

### User-level (cross-project shared)

- `Preference`: User preferences
- `Concept`: General concepts
- `Habit`: Work habits

### Project-level (project isolated)

- `Decision`: Project decisions
- `Episode`: Development episodes
- `File`: File descriptions
- `Architecture`: Architecture designs

## Storage Locations

- **User-level**: `~/.claude-memory/` (Windows: `%APPDATA%/claude-memory/`)
- **Project-level**: `{project-root}/.claude/memory/`

## License

MIT License - see LICENSE file for details.
