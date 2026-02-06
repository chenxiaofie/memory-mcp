#!/usr/bin/env python
"""最简化测试 - 不使用 TextIOWrapper"""
import sys
import os

# 不使用任何包装器，直接读取 stdin
try:
    if hasattr(sys.stdin, 'buffer'):
        data = sys.stdin.buffer.read()
    else:
        data = sys.stdin.read()
except:
    pass

# 输出空 JSON
sys.stdout.write("{}\n")
sys.stdout.flush()

# 直接退出
os._exit(0)
