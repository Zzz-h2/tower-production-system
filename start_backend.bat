@echo off
cd /d "E:\budy date\project one\tower_production_system\backend"
set MYSQL_PASSWORD=123456
set "PYTHONPATH=E:\budy date\project one\tower_production_system\backend"

echo [1/3] 确保本地 MySQL 服务已启动（服务名：MySQL80）...
sc query MySQL80 >nul 2>&1
if errorlevel 1 (
    echo   [警告] 未找到服务 MySQL80，跳过自动启动；请确认 MySQL 已安装或服务名是否不同。
    goto mysql_done
)
sc query MySQL80 | findstr /i "RUNNING" >nul 2>&1
if not errorlevel 1 (
    echo   MySQL80 已在运行，无需启动。
    goto mysql_wait
)
echo   MySQL80 未运行，正在尝试启动...
net start MySQL80 >nul 2>&1
if errorlevel 1 powershell -NoProfile -Command "Start-Service MySQL80" >nul 2>&1
if errorlevel 1 (
    echo   [错误] 启动 MySQL80 失败：通常是当前窗口没有管理员权限。
    echo   处理方式1：右键本脚本，选择「以管理员身份运行」后重试。
    echo   处理方式2：在管理员 CMD 中手动执行 net start MySQL80
    echo   处理方式3：管理员执行 sc config MySQL80 start= auto ，设为一劳永逸的开机自启。
    echo   现在仍会继续启动后端，但数据库相关请求会返回 500。
)
goto mysql_wait

:mysql_wait
echo   等待 MySQL 端口 3306 就绪（最多 60 秒）...
setlocal enabledelayedexpansion
set /a _mtry=0
:mysql_wait_loop
set /a _mtry+=1
netstat -ano | findstr ":3306" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo   MySQL 3306 已就绪（第 !_mtry! 次探测）。
    endlocal
    goto mysql_done
)
if !_mtry! GEQ 30 (
    echo   [警告] 等待 60 秒后 3306 仍未监听，继续启动后端（请检查 MySQL80 是否正常运行）。
    endlocal
    goto mysql_done
)
timeout /t 2 /nobreak >nul
goto mysql_wait_loop

:mysql_done
echo [2/3] 释放 8000 端口上所有监听（同时清 0.0.0.0 与 127.0.0.1，避免 rogue 抢占 localhost）...
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   杀掉占用 8000 的 PID %%p
    taskkill /f /t /pid %%p >nul 2>&1
)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"(Name='python.exe' or Name='python3.12.exe' or Name='python3.exe') and CommandLine like '%%app.main:app%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 2 /nobreak >nul

echo [3/3] 启动标准后端 0.0.0.0:8000 (--reload) ...
echo   看到 "Uvicorn running on http://0.0.0.0:8000" 即启动成功，localhost 流量将连到本标准后端。
echo   若报错（如 No module named app / Address already in use），请把上面的红色文字发我。
"E:\budy date\project one\tower_production_system\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
