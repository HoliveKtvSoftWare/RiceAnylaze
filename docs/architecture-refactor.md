# 后端架构整理（2026-09-22）

用户已批准：按业务模块组织，基础设施单独隔离；本文落实对话中已通过的设计。

## 不变量

- 保持所有 HTTP 路径、方法、认证、请求与响应字段、错误状态和下载格式。
- 保持 PostgreSQL 配置、表模型、数据和已保存文件路径。不执行数据库迁移或业务数据清理。
- 保持 10 项任务配置、native/fork 两套推理运行时、掩码几何及指标口径。
- 保持单线程 FIFO 队列与启动恢复规则；不引入 Redis、RQ 或新的运行依赖。
- 保持 RiceAnylaze / RiceAnylazeWeb 和工作区顶层的两份文档。验收后停止测试服务。
- 现有未提交修改是本次基线，不能重置、覆盖或混入提交；本次工作保留在本地分支供审阅。

## 模块和依赖

`api/routers` 负责 FastAPI 参数、认证与响应。`features` 负责编排用例，通过注入的 repository 访问数据库，通过 storage 处理磁盘文件。`domain` 包含无 Web/数据库依赖的计算。`infrastructure` 实现数据库、文件与推理环境适配。

领域计算允许使用现有 NumPy/OpenCV/Shapely 等数值依赖；“仅标准库”的初稿限制与现有算法冲突，不为目录整理重写算法。

```text
app/
  main.py                         应用入口，组装路由/静态文件/生命周期
  api/deps.py                     会话、当前用户和业务服务依赖
  api/routers/{auth,analysis,excel,export}.py
  features/
    analysis/{service,history_service,statistics_service,file_service,queue}.py
    export/{service,excel,schemas}.py
    task_catalog/{catalog,types}.py
  domain/
    geometry/                     轮廓/拓扑/side 归属
    analysis/metrics.py           茎秆/剑叶指标
  infrastructure/
    database/{session,migrations,repositories}.py
    storage/{files,previews,results}.py
    inference/                    native、sidecar、结果转换与预览渲染
  auth/                           fastapi-users 适配
  models/                         SQLModel 实体，表不变
  core/config.py                  配置；core/tasks.py 为旧任务目录兼容入口
deploy/
  runtime/                        启动/状态与运行时构建
  maintenance/                    数据修复/清理（不自动执行）
  experiments/                    离线对比、评测、历史训练参考
  docs/                           部署与模型说明
tests/{unit,integration,e2e}/      按测试边界归类
```

## 迁移决策

- 数据库唯一实现放在 `infrastructure/database/session.py`，保留 async 会话和 sync 引擎。旧 `database/session.py` 与 `auth/db.py` 仅兼容转发；auth/db 仍提供认证库适配，不能直接删除。
- 队列和任务状态的语义保持；业务用例负责状态持久化，推理模块只生成文件结果。
- old `app/services`、`api/endpoints` 及脚本命令是兼容边界；内部生产代码改用新路径。兼容文件只转发，不复制实现。旧模块的可变队列状态必须与新模块共享。
- 配置 `.env` 定位锚定后端根目录；已有 storage/model 相对路径表示保持，以免历史数据断链。命令脚本仍从后端根启动。
- 旧 RQ worker 未被当前启动链调用，归档到 deploy/legacy，保留原命令入口作为兼容包装，不激活、不删除数据。
- 不为目录树创建没有用途的空抽象。异常与日志仅承担实际需要的框架边界职责。

## 验收

先记录原始 OpenAPI 合约及 64 项测试基线，再迁移。验证用户隔离、分组查询、上传/批次/删除、FIFO/失败继续/启动恢复、几何和指标、Excel 与 JSON 导出、同源静态资源。真实 native 与 OUR 推理用独立临时输出比较结构与指标，不往正式数据库插入任务。使用隔离测试数据库和文件验证写操作，不自动启动正式应用的恢复队列。所有验证输出和源码快照保存在 `.run/`。

## 回滚

本次分支 `refactor/backend-architecture-20260922`，基线源码快照 `.run/architecture-baseline-20260922.zip`（不包含 .env、权重、业务数据或 git）。工作区文档另有 `.run/workspace-*-before-refactor.md`。回滚时逐项对比恢复，不使用 reset --hard 或覆盖整个用户工作区。

## 实际阅读入口

业务代码已迁入新目录，旧 `services` / `api/endpoints` 文件只负责转发。新增或修改功能时沿以下顺序查找：

1. `api/routers/analysis.py` → `features/analysis/history_service.py`、`statistics_service.py` 或 `file_service.py`。
2. 上传完成后进入 `features/analysis/queue.py` → `service.py` → `infrastructure/inference/`。
3. 导出进入 `features/export/service.py` → `excel.py` → `domain/analysis/metrics.py`。
4. 历史、导出、删除共用 `infrastructure/database/repositories.py`；文件读取和预览在 `infrastructure/storage/`。

不新增没有实际用途的 errors/logging 空壳模块；现有 HTTP 错误格式保持原样。
验收证据和测试命令见 [重构验收记录](architecture-refactor-verification.md)。
