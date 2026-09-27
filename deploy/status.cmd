@echo off
call "%~dp0runtime\status.cmd" %*
exit /b %errorlevel%
