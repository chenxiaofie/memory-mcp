@echo off
REM Memory MCP 安装脚本 (Windows)

echo === Memory MCP 安装脚本 ===
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python，请先安装 Python 3.10+
    exit /b 1
)

REM 创建虚拟环境
echo 1. 创建虚拟环境...
if not exist venv (
    python -m venv venv
)

REM 激活虚拟环境
echo 2. 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装依赖
echo 3. 安装依赖...
pip install -e . --quiet

echo.
echo === 安装完成 ===
echo.
echo 下一步：配置 Claude Code 连接此 MCP 服务
echo 运行以下命令：
echo.
echo   claude mcp add memory-mcp -- "%CD%\venv\Scripts\python.exe" "%CD%\run.py"
echo.
echo 或手动编辑 Claude Code 设置。
