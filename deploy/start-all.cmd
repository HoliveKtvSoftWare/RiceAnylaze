@echo off
call "%~dp0runtime\start-all.cmd" %*
exit /b %errorlevel%
