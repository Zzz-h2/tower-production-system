@echo off
cd /d "E:\budy date\project one\tower_production_system\backend"
set MYSQL_PASSWORD=123456
"E:\budy date\project one\tower_production_system\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
pause
