@echo off
cd /d "E:\budy date\project one\tower_production_system\frontend"
rem 释放 5173 端口旧进程（确保 vite 固定在 5173，不会漂移到 5174）
echo 准备释放 5173 端口旧进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1
rem 等待端口完全释放（旧进程关闭后 socket 释放有延迟，直接 start 会误判仍占用）
timeout /t 2 /nobreak >nul
rem --strictPort 若仍被占用则直接报错，绝不静默换端口；--force 强制重新优化依赖，确保加载最新代码/依赖
start "TowerFrontend-Vite" "C:\Users\zzzH\.workbuddy\binaries\node\versions\22.22.2\node.exe" "E:\budy date\project one\tower_production_system\frontend\node_modules\vite\bin\vite.js" --port 5173 --strictPort --force
timeout /t 3 /nobreak >nul
start "" "http://localhost:5173"
echo 前端已启动，浏览器将打开 http://localhost:5173
pause
