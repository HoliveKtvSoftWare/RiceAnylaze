@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  Rice_system - 启动 FastAPI 后端 0.0.0.0:8000
rem  必须在 RiceAnylaze 目录下启动：.env、app_storage、models_yolo
rem  都按相对路径解析。
rem  不要加 --reload，受限环境下 reload 子进程会 EPERM。
rem ============================================================
set "PY=D:\Anaconda\envs\fastapi\python.exe"
set "APP_DIR=%~dp0..\.."
set "YOLO_CONFIG_DIR=%APP_DIR%\.ultralytics"

if not exist "%PY%" (
  echo [错误] 找不到 Python 解释器: %PY%
  exit /b 1
)
if not exist "%APP_DIR%\models_yolo\yolov8s-1.pt" echo [警告] 缺少模型文件 %APP_DIR%\models_yolo\yolov8s-1.pt，推理任务会全部失败

cd /d "%APP_DIR%"
echo [启动] 后端 uvicorn app.main:app -^> http://0.0.0.0:8000    接口文档 http://127.0.0.1:8000/docs
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
endlocal

