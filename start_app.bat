@echo off
rem ============================================================
rem Tower Production System - One-click launcher
rem Double-click to start the app.
rem 启动前会先释放 8000 / 5173 旧进程，避免旧后端（尤其 127.0.0.1 绑定的）
rem 抢占 localhost 导致前端命中旧代码；随后以最新代码启动。
rem Close the two server windows to stop the app.
rem ============================================================

set MYSQL_PASSWORD=123456
echo Starting Tower Production System...

rem --- 释放并启动后端 (FastAPI :8000) ---
rem 先杀 8000 旧进程（含 --reload 父子进程），避免 127.0.0.1 旧后端抢占 localhost
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%p >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"(Name='python.exe' or Name='python3.12.exe' or Name='python3.exe') and CommandLine like '%%app.main:app%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 2 /nobreak >nul
echo Starting backend on :8000...
start "TowerBackend" /d "E:\budy date\project one\tower_production_system\backend" "E:\budy date\project one\tower_production_system\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

rem --- 释放并启动前端 (Vite :5173) ---
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1
timeout /t 2 /nobreak >nul
echo Starting frontend on :5173...
start "TowerFrontend" /d "E:\budy date\project one\tower_production_system\frontend" cmd /k "npm run dev"

rem --- wait until both are ready, then open browser ---
echo Waiting for servers to be ready...
powershell -NoProfile -Command "$max=90;$i=0;while($i -lt $max){try{$a=(New-Object System.Net.Sockets.TcpClient('127.0.0.1',8000)).Connected;$b=(New-Object System.Net.Sockets.TcpClient('127.0.0.1',5173)).Connected}catch{$a=$false;$b=$false};if($a -and $b){Write-Host 'Servers ready';exit 0}Start-Sleep -Seconds 1;$i++}Write-Host 'Wait timeout (check server windows for errors)';exit 1"

echo Opening browser...
start "" "http://localhost:5173"

exit /b
