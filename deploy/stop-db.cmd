@echo off
call "%~dp0runtime\stop-db.cmd" %*
exit /b %errorlevel%
