@echo off
cd /d "E:\budy date\project one\tower_production_system\backend"
set MYSQL_PASSWORD=123456

rem ===== 防重入 + 防 rogue：后端统一使用 0.0.0.0:8000 单例，绝不拉新端口 =====
rem 检测标准后端 0.0.0.0:8000 是否已在监听
netstat -ano 2>nul | findstr "LISTENING" | findstr "0.0.0.0:8000" >nul
set GOOD_UP=%errorlevel%
rem 检测漏 --host 的 rogue 127.0.0.1:8000 是否也在监听
netstat -ano 2>nul | findstr "LISTENING" | findstr "127.0.0.1:8000" >nul
set ROGUE_UP=%errorlevel%

if %GOOD_UP%==0 (
  if %ROGUE_UP%==0 (
    echo [info] 检测到 rogue(127.0.0.1:8000) 正在抢占 localhost，仅清理 rogue，保留标准后端。
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr "127.0.0.1:8000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%p >nul 2>&1
    goto :already
  )
  echo [skip] 0.0.0.0:8000 标准后端已在运行，跳过启动（防重入，避免双实例/抢端口）。
  goto :already
)

rem 没有标准后端：清理一切 8000 监听器（含 rogue / 端口残留），再启动唯一标准实例
echo [info] 清理 8000 旧/rogue 进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /t /pid %%p >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"(Name='python.exe' or Name='python3.12.exe' or Name='python3.exe') and CommandLine like '%%app.main:app%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 2 /nobreak >nul

echo [start] 启动标准后端 0.0.0.0:8000 (--reload)...
"E:\budy date\project one\tower_production_system\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
:already
pause
