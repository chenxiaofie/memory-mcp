#!/usr/bin/env python
"""
启动 Memory MCP 服务的入口脚本
"""

import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory_mcp.server import run

if __name__ == "__main__":
    run()
