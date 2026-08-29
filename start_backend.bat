@echo off
cd /d "E:\budy date\project one\tower_production_system\backend"
set MYSQL_PASSWORD=123456
set "PYTHONPATH=E:\budy date\project one\tower_production_system\backend"

echo [1/2] 释放 8000 端口上所有监听（同时清 0.0.0.0 与 127.0.0.1，避免 rogue 抢占 localhost）...
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   杀掉占用 8000 的 PID %%p
    taskkill /f /t /pid %%p >nul 2>&1
)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"(Name='python.exe' or Name='python3.12.exe' or Name='python3.exe') and CommandLine like '%%app.main:app%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/2] 启动标准后端 0.0.0.0:8000 (--reload) ...
echo   看到 "Uvicorn running on http://0.0.0.0:8000" 即启动成功，localhost 流量将连到本标准后端。
echo   若报错（如 No module named app / Address already in use），请把上面的红色文字发我。
"E:\budy date\project one\tower_production_system\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
