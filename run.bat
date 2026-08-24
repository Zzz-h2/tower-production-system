@echo off
chcp 65001 >nul
title 塔筒生产进度管控系统 (FastAPI + Vue3)

echo ============================================
echo   塔筒生产进度管控系统 v1.1
echo   Tower Production Progress Control System
echo ============================================
echo.

set MYSQL_PASSWORD=123456

rem ===== 释放旧进程（关键：避免 127.0.0.1 旧后端抢占 localhost 导致前端命中旧代码）=====
echo [0/2] 释放 8000 / 5173 旧进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /f /t /pid %%p >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"(Name='python.exe' or Name='python3.12.exe' or Name='python3.exe') and CommandLine like '%%app.main:app%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 2 /nobreak >nul

rem ===== 启动后端 (FastAPI :8000) =====
rem --host 0.0.0.0 保证 localhost 命中本后端（不会被 127.0.0.1 旧进程抢占）；--reload 令代码改动保存即自动重载，始终运行最新代码
echo [1/2] 启动后端 FastAPI :8000 ...
start "TowerBackend" /d "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

rem ===== 启动前端 (Vite :5173) =====
echo [2/2] 启动前端 Vite :5173 ...
start "TowerFrontend" /d "%~dp0frontend" cmd /k "npm run dev"

echo.
echo 后端: http://localhost:8000    前端: http://localhost:5173
echo 等待两个服务就绪后，浏览器访问 http://localhost:5173
start "" "http://localhost:5173"

exit /b
