@echo off
chcp 65001 >nul
title Tower Production System (FastAPI + Vue3, MySQL mode)
cd /d "%~dp0"

rem ===== MySQL connection settings (password set inline below) =====
set MYSQL_HOST=127.0.0.1
set MYSQL_USER=root
set MYSQL_PASSWORD=123456
set MYSQL_DATABASE=tower_production
set MYSQL_PORT=3306

echo.
echo Connecting to MySQL %MYSQL_HOST%:%MYSQL_PORT% / %MYSQL_DATABASE%
echo Starting backend :8000 and frontend :5173 ...
echo.

rem ===== 启动后端 (FastAPI :8000) =====
start "TowerBackend" /d "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

rem ===== 启动前端 (Vite :5173) =====
start "TowerFrontend" /d "%~dp0frontend" cmd /k "npm run dev"

echo 浏览器访问 http://localhost:5173
start "" "http://localhost:5173"
exit /b
