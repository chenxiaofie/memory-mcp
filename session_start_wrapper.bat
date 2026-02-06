@echo off
:: 这个批处理脚本会立即返回，而Python脚本在后台运行
:: Claude Code 调用这个脚本，脚本立即退出，不会卡住

:: 读取stdin并丢弃（因为Claude Code会通过stdin传递数据）
:: 但我们不需要处理它，让Python脚本自己处理

:: 直接调用Python脚本，它会自己处理stdin
"C:\Users\admin\AppData\Roaming\claude-memory\venv\Scripts\python.exe" "C:\Users\admin\AppData\Roaming\claude-memory\session_start.py"
