@echo off
title Mark-LIV Assistant
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Starting Mark-LIV Assistant...
python -X utf8 main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
