@echo off
cd /d "%~dp0"
py -3 server_manager.py
if errorlevel 1 pause
