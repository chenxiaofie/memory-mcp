@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo Failed to create venv, trying python3...
    python3 -m venv venv
)
echo Activating venv...
call venv\Scripts\activate.bat
echo Installing dependencies...
pip install mcp chromadb sentence-transformers pydantic
echo Done!
pause
