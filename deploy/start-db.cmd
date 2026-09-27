@echo off
call "%~dp0runtime\start-db.cmd" %*
exit /b %errorlevel%
