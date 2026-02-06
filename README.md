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

Run the `install.bat` file in the project root directory:

```bash
# Double-click to run or execute from command line
install.bat
```

### Mac/Linux One-click Installation

Run the `install.sh` file in the project root directory:

```bash
# Execute from command line
chmod +x install.sh
./install.sh
```

### Manual Installation

```bash
cd .claude/memory-mcp

# Create virtual environment
python -m venv venv310

# Activate virtual environment
# Windows:
venv310\Scripts\activate
# Mac/Linux:
source venv310/bin/activate

# Install dependencies
pip install -e .
```

## Configure Claude Code

### 1. MCP Service Configuration

#### Method 1: Add using command line (recommended)

```bash
claude mcp add memory-mcp -- python -m src.server
```

#### Method 2: Manual configuration in settings.json

Edit `~/.claude/settings.json` (global configuration):

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

### 2. Hooks Functionality

The project provides 4 automated hooks to implement complete session lifecycle management:

| Hook Name          | File                     | Function Description                                                                 |
|-------------------|--------------------------|-------------------------------------------------------------------------------------|
| SessionStart      | `session_start.py`       | Automatically creates a scenario when a session starts and begins monitoring the terminal lifecycle |
| UserPromptSubmit  | `auto_save.py`           | Automatically saves user messages to the memory system when they submit a prompt    |
| Stop              | `save_response.py`       | Saves assistant responses to the memory system when the session stops               |
| SessionEnd        | `session_end.py`         | Sends a close signal to the monitoring process when the session ends, which is responsible for closing the scenario and generating a summary |

### 3. Verify Configuration

```bash
# Check MCP server status
claude mcp list

# Expected output
Checking MCP server health...
playwright: npx @playwright/mcp@latest - ✓ Connected
memory-mcp: /path/to/your/venv/bin/python -m src.server - ✓ Connected
```

## Tools List

### Message Cache

- `memory_cache_message`: Cache messages

### Episode Management

- `memory_start_episode`: Start a new episode
- `memory_close_episode`: Close an episode
- `memory_get_current_episode`: Get current episode

### Entity Management

- `memory_add_entity`: Add entity
- `memory_confirm_entity`: Confirm candidate entity
- `memory_reject_candidate`: Reject candidate
- `memory_deprecate_entity`: Deprecate entity
- `memory_get_pending`: Get pending entities

### Retrieval

- `memory_recall`: Comprehensive retrieval
- `memory_search_by_type`: Search by type
- `memory_get_episode_detail`: Get episode detail

### Statistics

- `memory_stats`: Get statistics

## Entity Types

### User-level (cross-project shared)

- `Preference`: User preferences
- `Concept`: General concepts
- `Habit`: Work habits

### Project-level (project isolated)

- `Decision`: Project decisions
- `Episode`: Development scenes
- `File`: File descriptions
- `Architecture`: Architecture designs

## Storage Locations

- User-level: `~/.claude-memory/` (Windows: `%APPDATA%/claude-memory/`)
- Project-level: `{project}/.claude/memory/`

## Example Usage

```
# Start a new task
Claude call: memory_start_episode("Login Function Development", ["auth"])

# Record a decision
Claude call: memory_add_entity("Decision", "Adopt JWT + Redis solution", "Consider distributed deployment")

# Retrieve history
Claude call: memory_recall("Login scheme")

# Close task
Claude call: memory_close_episode("Completed JWT login function development")
```

## License

MIT License - see LICENSE file for details.
