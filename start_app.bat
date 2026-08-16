@echo off
rem ============================================================
rem Tower Production System - One-click launcher
rem Double-click to start the app. SAFETY: this script NEVER
rem kills any process. It only starts a service when its port
rem is free, so re-running it is safe and idempotent.
rem Close the two server windows to stop the app.
rem ============================================================

set MYSQL_PASSWORD=123456
echo Starting Tower Production System...

rem --- backend (FastAPI :8000) ---
netstat -aon | findstr /r ":8000 .*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo Starting backend on :8000...
    start "TowerBackend" /d "E:\budy date\project one\tower_production_system\backend" "E:\budy date\project one\tower_production_system\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
) else (
    echo Backend already running on :8000, skip.
)

rem --- frontend (Vite :5173) ---
netstat -aon | findstr /r ":5173 .*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo Starting frontend on :5173...
    start "TowerFrontend" /d "E:\budy date\project one\tower_production_system\frontend" cmd /k "npm run dev"
) else (
    echo Frontend already running on :5173, skip.
)

rem --- wait until both are ready, then open browser ---
echo Waiting for servers to be ready...
powershell -NoProfile -Command "$max=90;$i=0;while($i -lt $max){try{$a=(New-Object System.Net.Sockets.TcpClient('127.0.0.1',8000)).Connected;$b=(New-Object System.Net.Sockets.TcpClient('127.0.0.1',5173)).Connected}catch{$a=$false;$b=$false};if($a -and $b){Write-Host 'Servers ready';exit 0}Start-Sleep -Seconds 1;$i++}Write-Host 'Wait timeout (check server windows for errors)';exit 1"

echo Opening browser...
start "" "http://localhost:5173"

exit /b
