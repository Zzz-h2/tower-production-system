@echo off
chcp 65001 >nul
title 塔筒生产进度管控系统

echo ============================================
echo   塔筒生产进度管控系统 v1.0
echo   Tower Production Progress Control System
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 安装依赖
echo [1/2] 检查并安装依赖...
pip install -r requirements.txt -q

:: 初始化配置
echo [2/2] 启动系统...
echo.

:: 启动 Streamlit
streamlit run app.py --server.port 8501 --server.headless false

pause
