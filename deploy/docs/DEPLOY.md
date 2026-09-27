# 部署与本地运行

## 目录

工作区顶层只保留两个目录：

* `RiceAnylaze/`：FastAPI、模型、旁路运行时、部署脚本和运行数据。
* `RiceAnylazeWeb/`：Vue 3 + Vite 前端。

当前数据库直接连接本机 PostgreSQL 18 的 `rice_analysis_db`（`127.0.0.1:5432`）。

## 环境要求

* Python：`D:\Anaconda\envs\fastapi\python.exe`
* Node.js：可执行 `node` 和 `npm`
* 本机 PostgreSQL 18 服务监听 `127.0.0.1:5432`
* 后端依赖已安装：`RiceAnylaze\requirements`
* 模型权重位于 `RiceAnylaze\models_yolo\`

后端连接串位于 `RiceAnylaze\.env`。不要再启动或初始化独立的 `pgsql_data` 集群。

## 启动

首次或前端代码变更后构建：

```bat
cd /d D:\Code\Rice_system\RiceAnylazeWeb
npm run build
```

一键启动后端和前端（数据库只做就绪检查）：

```bat
cd /d D:\Code\Rice_system
RiceAnylaze\deploy\start-all.cmd
```

也可以分别启动：

```bat
RiceAnylaze\deploy\start-backend.cmd
RiceAnylaze\deploy\start-frontend.cmd
```

访问前端：`http://localhost:5173/`；接口文档：`http://localhost:8000/docs`。

状态检查：

```bat
RiceAnylaze\deploy\status.cmd
```

停止脚本不会关闭本机 PostgreSQL；本机数据库由 Windows 服务管理。

## 推理运行时

`RiceAnylaze/.ultra_refine/` 是带 Mask Refinement 检测头的旁路运行时，
`RiceAnylaze/.pylibs/` 是旁路依赖，均由 `RiceAnylaze/app/core/config.py` 按后端目录自动定位。
运行时构建或检查：

```bat
cd /d D:\Code\Rice_system\RiceAnylaze
D:\Anaconda\envs\yolo\python.exe deploy\build_refine_ultralytics.py --check
```

检测头说明见 `RiceAnylaze/deploy/REFINE_HEAD.md`。

## 数据与备份

* PostgreSQL 数据库：本机服务中的 `rice_analysis_db`，建议用 `pg_dump` 备份。
* 上传原图与分析结果：`RiceAnylaze\app_storage\`。
* 模型：`RiceAnylaze\models_yolo\`，不纳入 git，需单独备份。

## 常见问题

* 页面 502：确认后端已在 8000 端口运行，再执行 `RiceAnylaze\deploy\status.cmd`。
* `/static` 图片 404：必须从 `RiceAnylaze` 目录启动后端，以便正确读取 `.env` 的相对路径。
* 数据库认证失败：检查本机 PostgreSQL 服务、`RiceAnylaze\.env` 中的 `DATABASE_URL` 和账户密码。
