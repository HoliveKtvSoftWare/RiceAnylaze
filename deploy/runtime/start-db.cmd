@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  Rice_system - 检查本机 PostgreSQL 服务 127.0.0.1:5432
rem  数据库由 Windows PostgreSQL 服务管理，项目不再启动独立数据目录。
rem ============================================================
set "PGBIN=C:\Program Files\PostgreSQL\18\bin"
set "PGPORT=5432"

"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p %PGPORT% >nul 2>&1
if errorlevel 1 (
  echo [错误] 本机 PostgreSQL 未就绪: 127.0.0.1:%PGPORT%
  exit /b 1
)
echo [正常] 本机 PostgreSQL 已就绪: 127.0.0.1:%PGPORT%
endlocal

