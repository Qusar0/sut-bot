@echo off
rem Запуск Bonch Free локально: Cloudflare-туннель (публичный HTTPS для Mini App) + бот.
rem Автоперезапуск при сбое. Логи -> data\bot.log
cd /d "%~dp0"
:loop
".venv\Scripts\python.exe" -X utf8 local_run.py >> "data\bot.log" 2>&1
timeout /t 5 /nobreak >nul
goto loop
