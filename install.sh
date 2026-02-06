#!/bin/bash
# Memory MCP 安装脚本 (Mac/Linux)

echo "=== Memory MCP 安装脚本 ==="
echo

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 Python，请先安装 Python 3.10+"
    exit 1
fi

# 创建虚拟环境
echo "1. 创建虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# 激活虚拟环境
echo "2. 激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "3. 安装依赖..."
pip install -e . --quiet

echo
echo "=== 安装完成 ==="
echo
echo "下一步：配置 Claude Code 连接此 MCP 服务"
echo "运行以下命令："
echo
echo "  claude mcp add memory-mcp -- \"$(pwd)/venv/bin/python\" \"$(pwd)/run.py\""
echo
echo "或手动编辑 Claude Code 设置。"
