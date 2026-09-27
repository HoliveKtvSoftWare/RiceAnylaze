@echo off
call "%~dp0runtime\start-frontend.cmd" %*
exit /b %errorlevel%
