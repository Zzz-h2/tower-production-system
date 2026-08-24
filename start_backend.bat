@echo off
cd /d "E:\budy date\project one\tower_production_system\backend"
set MYSQL_PASSWORD=123456
rem 释放 8000 旧后端（含 --reload 父子进程）：先按端口杀监听进程，再按命令行补杀所有 uvicorn 进程。
rem 注意：venv 后端进程名是 python3.12.exe（不是 python.exe），命令行补杀必须覆盖这两种名字，否则旧后端杀不掉、新后端因端口占用起不来，前端会命中旧代码。
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%p >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"(Name='python.exe' or Name='python3.12.exe' or Name='python3.exe') and CommandLine like '%%app.main:app%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
rem 等待端口完全释放（旧进程关闭后 socket 释放有延迟，直接启动会误判仍占用）
timeout /t 2 /nobreak >nul
rem --host 0.0.0.0 保证 localhost 命中本后端（不会被 127.0.0.1 旧进程抢占）；--reload 令代码改动保存即自动重载，始终运行最新代码
"E:\budy date\project one\tower_production_system\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
