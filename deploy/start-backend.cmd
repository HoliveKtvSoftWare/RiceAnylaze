@echo off
call "%~dp0runtime\start-backend.cmd" %*
exit /b %errorlevel%
