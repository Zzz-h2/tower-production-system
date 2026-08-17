@echo off
chcp 65001 >nul
title 塔筒生产进度管控系统 (FastAPI + Vue3)

echo ============================================
echo   塔筒生产进度管控系统 v1.1
echo   Tower Production Progress Control System
echo ============================================
echo.

set MYSQL_PASSWORD=123456

rem ===== 启动后端 (FastAPI :8000) =====
echo [1/2] 启动后端 FastAPI :8000 ...
start "TowerBackend" /d "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

rem ===== 启动前端 (Vite :5173) =====
echo [2/2] 启动前端 Vite :5173 ...
start "TowerFrontend" /d "%~dp0frontend" cmd /k "npm run dev"

echo.
echo 后端: http://localhost:8000    前端: http://localhost:5173
echo 等待两个服务就绪后，浏览器访问 http://localhost:5173
start "" "http://localhost:5173"

exit /b
