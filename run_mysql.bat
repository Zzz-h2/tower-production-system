@echo off
chcp 65001 >nul
title Tower Production System (MySQL mode)
cd /d "%~dp0"

rem ===== install dependencies (official PyPI to avoid mirror 403) =====
echo Checking / installing dependencies...
python -m pip install -r requirements.txt -i https://pypi.org/simple

rem ===== MySQL connection settings (password set inline below) =====
set MYSQL_HOST=127.0.0.1
set MYSQL_USER=root
set MYSQL_PASSWORD=123456
set MYSQL_DATABASE=tower_production
set MYSQL_PORT=3306

echo.
echo Connecting to MySQL %MYSQL_HOST%:%MYSQL_PORT% / %MYSQL_DATABASE%
echo Starting Streamlit... open http://localhost:8501 in your browser
echo.

python -m streamlit run app.py --server.port 8501
pause
