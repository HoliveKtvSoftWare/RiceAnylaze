# 后端适配新版前端（RiceAnylazeWeb@main）

## 为什么需要这次适配

前端仓库 `RiceAnylazeWeb` 的 `main` 分支是对着**后端 `origin/main`（4d380a0）**写的；
而本仓库的重构分支 `chen` 基于 `c9f6b6a`，落后 4 个提交，正好缺掉前端依赖的全部新接口：

| 后端提交 | 前端依赖的变化 |
|---|---|
| `2e4c85a` 优化模型选择、导出功能 | `GET /analysis/models`、上传 `model_name`、`Analysis.model_used` / `error_message` |
| `8f26d8e` 优化代码 | Excel 改为 **blob 下载 + 异步任务**（`/excel/tasks/{id}`、`/excel/download/{id}`） |
| `4d380a0` 文件命名权移交后端 | 导出文件名由后端给出（中文名 + 时间戳） |
| `632f351` 修改登陆过期时长 | JWT 有效期 1 小时 → 24 小时 |

那 4 个提交是写在**旧目录结构**（`app/api/endpoints/`、`app/services/`）上的，
而 `chen` 已经把它们掏空成兼容转发器，所以不能直接 merge，只能把功能**迁移**进新分层。

## 改了什么

### 1. 模型选择（对齐 `GET /analysis/models`）

前端的 `<select>` 把 `name` 同时当作 value 和展示文本，并把选中的 `name`
原样作为 `model_name` 回传。因此：

- `app/features/task_catalog/catalog.py`：新增 `list_models()` / `default_model_name()`；
  `resolve_task_type()` 同时接受 **task key** 与**中文显示名**，未知值回退 `stem`。
- `app/features/analysis/history_service.py`：`get_available_models(group=None)`，
  返回 `{"models": [{name, path, key, group}], "default": name}`，`group` 可选过滤。
- `app/api/routers/analysis.py`：新增 `GET /models`；`/upload`、`/upload/batch`
  接受 `model_name`（优先）、`task_type`（兼容旧客户端）、`batch_id`、`batch_name`。

模型注册表**继续由 `task_catalog` 单一提供**，没有引入上游那套 `.env` 里的
`YOLO_MODELS` —— 否则会出现两份互相打架的模型清单。

### 2. 分析记录新增字段

`Analysis` 增加 `model_used`、`error_message`（`app/models/analysis.py`），
并按既有做法登记到启动时轻量迁移（`app/infrastructure/database/migrations.py`），
只在缺列时 `ADD COLUMN`，不动数据。历史接口相应返回 `modelUsed` / `errorMessage`。

失败原因由 `app/features/analysis/service.py::_summarize_error` 归一成中文，
模型权重缺失时前端会看到「未部署该模型: xxx」。

### 3. 批次名与批次复用

前端「选择多张单图」会给每张图发**同一个** `batch_id`（形如 `batch_1738..._ab12`，
不是 UUID），并期望历史按它折叠成批次。

- `UploadBatch` 增加 `name` 列（同步登记轻量迁移）。
- `app/features/analysis/file_service.py`：`_client_batch_uuid()` 用
  `uuid5(命名空间, "用户:批次串")` 把它稳定映射成 UUID —— 同一批次串必得同一个
  UUID，且天然按用户隔离，不会撞上 `batch_id` 的唯一约束。批次已存在则复用并累加
  `file_count`，不会为同一批写多条批次记录。
- 历史接口一次查出批次名（`BatchRepository.names_for`，避免 N+1），返回 `batchName`。

### 4. Excel 导出：blob + 异步任务

前端 `responseType` 是 `blob`，并从 `Content-Disposition` 取文件名，所以：

- **新增 `app/features/export/responses.py`**：`build_content_disposition()`（中文名按
  RFC 5987 同时给 ASCII 回退名和 `filename*=UTF-8''`）与流式响应构造函数。
- **新增 `app/features/export/tasks.py`**：内存任务注册表 + 后台线程。
  导出是 pandas/openpyxl 同步栈，放线程里才不会阻塞事件循环；注册表只在进程内，
  重启即失效（导出可重试，不值得为它引 Redis）。结果落盘在系统临时目录
  `rice_export_tasks/`，**刻意不放进 `STORAGE_PATH`** —— 那个目录挂在 `/static` 上。
- `app/features/export/service.py`：同步路径直接返回 xlsx 字节流；`asyncMode=true`
  时返回 `{success, taskId, pollUrl, downloadUrl}`。汇总/批量在未指定 `taskType`
  时按记录推断类型，混合类型报 400（列口径不相通，混在一张表里没有意义）。
- `app/api/routers/excel.py`：补 `GET /tasks/{task_id}`、`GET /download/{task_id}`。
- `app/main.py`：CORS 增加 `expose_headers=["Content-Disposition"]`，
  否则浏览器读不到导出文件名。

### 5. 其它

- `app/auth/backend.py`：JWT `lifetime_seconds` 3600 → 86400。
- `app/api/routers/export.py` + `service.py`：JSON 下载改由后端命名
  （样本名 + 时间戳，批量 ZIP 为 `N个文件_时间戳.zip`），复刻 `4d380a0`。
- `app/infrastructure/inference/native.py`：加载权重前先查文件是否存在，
  报错文案与 `_summarize_error` 对齐。

## 有意为之的行为变化

| 变化 | 原因 |
|---|---|
| `/excel/*` 由 `{filename, content: base64}` 改为**二进制 xlsx 字节流** | 前端用 `responseType:'blob'` 接；base64 JSON 会被当成 xlsx 存坏 |
| `/export/json/*` 的下载名由后端决定 | 复刻 `4d380a0`；前端不再拿到 UUID 文件名 |
| `/excel/summary` 不带 `taskType` 时导出**全部**已完成记录（要求同类型） | 新版前端不传 `taskType`；原来默认只导 `stem` 会静默漏记录 |

## 兼容性

- **没有删除任何原有接口**：基线快照 22 条路径全部保留，只新增 3 条
  （`/analysis/models`、`/excel/tasks/{id}`、`/excel/download/{id}`，共 25 条）。
- `task_type` 参数、`/analysis/tasks`、`/analysis/stats`、`/analysis/queue`
  等旧接口继续可用；新旧前端可同时对接。
- `app/services/*`、`app/core/tasks.py` 中的兼容转发仍共享同一份状态
  （只被测试引用的那几个已在后续死代码清理中删除）。

## 验证

```powershell
cd RiceAnylaze
D:\Anaconda\envs\fastapi\python.exe -B -m unittest discover -s tests -v   # 90 passed
D:\Anaconda\envs\fastapi\python.exe -B tests/e2e/verify_refactor.py       # 见下
```

`tests/e2e/verify_refactor.py` 原先断言「OpenAPI 与重构前快照逐字节一致」，
本次适配有意扩展了接口，该断言已改为更有意义的双重校验：

1. 基线里的 22 条路径**一条都不能少**（不破坏既有消费者）；
2. 新版前端需要的 16 条路径必须齐全。

所得报告：`{"baseline_paths": 22, "paths": 25, "removed_paths": [],
"frontend_routes_missing": [], "metric_and_workbook_cases": 18,
"real_leaf_metrics_identical": true, "legacy_dependency_violations": []}`

集成测试用隔离 SQLite + 进程内 ASGI 覆盖了：模型列表、`model_name` 上传与
`model_used` 落库、批次复用与 `batchName`、Excel 同步 blob（含
`filename*=UTF-8''`）、异步导出轮询到下载、以及跨用户隔离。
