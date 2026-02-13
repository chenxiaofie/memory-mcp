#!/usr/bin/env python
"""
初始化命令：预下载 sentence-transformers 模型
安装后运行一次即可：memory-mcp-init
"""

import sys
import os


def main():
    model_name = 'paraphrase-multilingual-MiniLM-L12-v2'
    print(f"[memory-mcp-init] Downloading model: {model_name}")
    print(f"[memory-mcp-init] This may take a few minutes on first run...")

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        # 验证模型可用
        model.encode("test")
        print(f"[memory-mcp-init] Model ready!")
    except Exception as e:
        print(f"[memory-mcp-init] Failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
