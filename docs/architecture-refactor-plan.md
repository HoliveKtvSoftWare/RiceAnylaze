# 后端模块迁移执行清单

依据：`architecture-refactor.md`。已批准设计的实施记录，不再设置二次审批门槛。

## 任务与验收

- [x] 0. 记录 64 项单元测试基线、源码快照、本地重构分支。
- [x] 1. 配置和数据库：唯一 session 实现；light migrations 分离；认证复用相同 async 依赖；模型表结构不动。
- [x] 2. 推理：原 yolo_inference 拆分 native、渲染、LabelMe、geometry；sidecar 子进程启动从 analysis_service 移出。task catalog 拆 types/catalog；保留原接口。
- [x] 3. 分析：薄路由 + service/history/statistics/file_service；SQL 查询进 repository；preview/文件和 URL 处理进 storage；queue 和 run_full_analysis 进业务模块。
- [x] 4. 导出：指标从 Excel 服务提取为无框架依赖计算；Excel/JSON 服务负责数据编排和格式；路由保持 HTTP 合约。
- [x] 5. 部署：实际实现迁往 runtime/maintenance/experiments/docs；旧命令做兼容包装，修正脚本根路径、sidecar 导入。旧 RQ 归档。
- [x] 6. 验证：原有测试、补充合约/持久化/导出测试、真实双运行时推理、独立审查、文档导航和更新日志。测试服务退出。

## 接口约束

- `get_async_session()` 单一函数对象供所有 Depends 与测试 override 使用。
- `AnalysisRepository(session)` 的 async 查询与写入供业务服务使用；同步 worker 使用同一模块定义的 sync engine 创建短事务。
- `run_system(...) -> (annotated_path, json_path)`、`run_full_analysis(...)`、`_run_via_sidecar(task, image_path, output_dir, basename)` 保持现有签名与参数。
- `TaskSpec` 所有字段、默认值和 list_tasks 输出保持不变。
- `ExcelService` 原公共方法、列顺序和 LabelMe JSON 内容保持；仅边界改造，不重算新指标。

## 风险检查记录

| 共享边界 | 决策 |
| --- | --- |
| 分析/导出均读 Analysis | 用同一个 repository 定义；查询始终包含用户过滤 |
| API/认证/测试覆写 session | 旧导入返回同一函数；禁止再创建会话工厂 |
| 旧队列测试 monkeypatch | 旧路径别名指向新模块，避免双份全局状态 |
| native 与 fork 共用后处理 | fork 只 importlib 加载无配置副作用的模块，保持独立环境 |
| sidecar/构建脚本移动 | 旧文件包装保持 __file__ 根推导明确；测试旧命令和新命令 |
| 当前 checkout 有大量未提交功能 | 基于当前文件快照，不从 HEAD 重建，不提交用户代码 |

## 进度

基线：`D:\Anaconda\envs\fastapi\python.exe -B -m unittest discover -s tests -v`，64/64 通过，输出 `.run/refactor-baseline-tests.log`。

最终验收：88/88 自动测试通过；22 条路径的完整 OpenAPI 一致；18 组指标/Excel 一致；native/fork 真实输出一致。详见 `architecture-refactor-verification.md`。
