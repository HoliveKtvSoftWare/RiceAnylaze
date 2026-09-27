# 后端架构重构验收（2026-09-22）

## 完成范围

业务实现已从旧 services/endpoints 迁入新目录；旧模块只做兼容转发。
数据库、文件、推理分别由 infrastructure 中的适配层管理，纯几何和指标位于 domain。
前端没有为此次后端重构调整接口。

| 层次 | 实现入口 |
|---|---|
| 应用组装 | `app/main.py` |
| HTTP 与认证 | `app/api/routers/{auth,analysis,excel,export}.py`、`app/api/deps.py` |
| 分析流程 | `app/features/analysis/{service,history_service,statistics_service,file_service,queue}.py` |
| 导出与请求结构 | `app/features/export/{service,excel,schemas}.py` |
| 模型注册 | `app/features/task_catalog/{catalog,types}.py` |
| 指标与几何 | `app/domain/analysis/metrics.py`、`app/domain/geometry/mask_geometry.py` |
| 数据库 | `app/infrastructure/database/{session,migrations,repositories}.py` |
| 存储 | `app/infrastructure/storage/{files,previews,results}.py` |
| 模型执行 | `app/infrastructure/inference/{native,labelme,renderer,runner,sidecar}.py` |
| 部署分类 | `deploy/{runtime,maintenance,experiments,docs,legacy}/` |

新代码没有反向依赖 `app/services`、`app/database`、`app/api/endpoints`、
`app/core/tasks.py` 这些兼容入口。队列与预览缓存的旧导入和新模块使用同一份状态。

## 验证结果

| 检查 | 结果 | 证据 |
|---|---|---|
| 单元与集成回归 | 88/88 通过 | `.run/refactor-tests-final.log` |
| 注册/登录/认证后历史 | 隔离 SQLite 实际 SQL + ASGI 请求通过 | `tests/integration/test_http_workflows.py` |
| 用户隔离与删除 | 外部用户记录不可读/删；所属记录文件和预览一起删除 | 同上、`test_analysis_repository.py` |
| 上传、单条/汇总/批量导出、静态预览 | 写入、入队、JSON/ZIP/XLSX 内容与预览读取通过 | 同上 |
| 任务持久化 | 成功与失败状态、开始/结束时间写入通过 | 同上 |
| API 合约 | 22 条路径及完整 OpenAPI 完全一致 | `.run/refactor-contract-report.json` |
| 指标与 Excel | 18 组计算值、列名/顺序、工作表单元格一致 | 同上 |
| 真实图片 native leaf | 161 个形状，JSON/JPG 逐字节一致 | `.run/inference-comparison/report.json` |
| 真实图片 fork leaf_our | 206 个形状，JSON/JPG 逐字节一致，mask_refine=true | 同上 |
| 真实剑叶结果指标 | native/fork 两份结果的指标计算与基线一致 | `.run/refactor-contract-report.json` |
| 编译 | app、deploy、tests、worker.py 的 compileall 通过 | 本次命令输出 |
| 独立审查 | 部署/推理、API/业务分离均通过；空白筛选回归已修复 | 本次审查记录 |

OpenAPI 基线为 `.run/openapi-before.json`，源代码基线为
`.run/architecture-baseline-20260922.zip`。基线包含重构前未提交的用户代码，
因此使用此快照而非 Git HEAD 判断兼容性。

## 运行方法

从 RiceAnylaze 目录运行：

```powershell
D:\Anaconda\envs\fastapi\python.exe -B -m unittest discover -s tests -v
D:\Anaconda\envs\fastapi\python.exe -B -m compileall -q app deploy tests worker.py
D:\Anaconda\envs\fastapi\python.exe -B tests/e2e/verify_refactor.py
D:\Anaconda\envs\fastapi\python.exe -B tests/e2e/compare_inference.py --image <真实图片路径>
```

后两条是本次迁移的手动基线检查，需要保留 .run 中的快照、对比结果和本机模型环境。
真实模型对比只对指定图片生成 .run 结果，不会提交正式分析任务。
集成测试使用专属 SQLite 文件与测试图片，结束后清理，不运行正式应用启动恢复逻辑。

## 边界与当前状态

- 未修改正式 PostgreSQL 数据、模型权重或已经保存的分析文件，也未运行维护删除脚本。
- 未对正式数据库账号与业务数据进行连接验收。TCP 检查显示 5432 接受连接；此结果不等于数据库认证成功。
- 8000/5173 拒绝 TCP 连接，前后端未启动；测试使用进程内 ASGI，不留下监听服务。
- 浏览器自动化仍返回 `unsupported Codex auth method: apikey`；终端、文件读写和补丁工具可用。
  本次验证不依赖浏览器自动化。
- 本地分支保持 `refactor/backend-architecture-20260922`，没有替用户提交、推送或合并。
  原有未提交修改保留；回退时应逐文件对比基线快照，不使用整体 reset。
