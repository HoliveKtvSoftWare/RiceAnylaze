# 分析大类（族）拆分说明

面向维护者：茎秆与剑叶的代码怎么分、改动落在哪个文件、怎么加第三个大类。

## 一句话

**不是两套代码，是一条共享流水线 + 每族一个「族定义」和一份「族指标」。**
茎秆和剑叶的差异全部表达成数据（`TaskSpec`），代码里没有 `if 是不是剑叶` 这种判断。

## 文件分工

```
app/
├─ domain/analysis/                      ← 纯计算，不碰 Web/DB/文件
│  ├─ metrics_common.py                  共享：鞋带公式、周长、单位换算   ⚠ 改动影响两族
│  └─ families/
│     ├─ stem.py                         ★ 茎秆指标算法
│     └─ leaf.py                         ★ 剑叶指标算法
└─ features/task_catalog/
   ├─ types.py                           共享：TaskSpec / TaskFamily      ⚠ 共享核心
   ├─ registry.py                        共享：聚合各族 + 全部查询接口    ⚠ 共享核心
   └─ families/
      ├─ stem.py                         ★ 茎秆：模型清单 + 导出列 + 后处理参数
      ├─ leaf.py                         ★ 剑叶：同上
      └─ __init__.py                     ALL_FAMILIES = (stem.FAMILY, leaf.FAMILY)
```

★ = 各方向的维护者只动自己那两个文件，日常改动不会冲突。

## 一个「族」要提供什么

`TaskFamily`（定义在 `types.py`）是共享核心与具体族之间**唯一的接口**：

| 字段 | 含义 |
|---|---|
| `key` | 族标识。**必须**与 `TaskSpec.group`、HTTP 的 `group` 查询参数一致（数据库历史数据 + 前端契约都靠它，不能改）|
| `label` | 中文名，前端与错误提示直接用 |
| `columns` | 导出列定义（key → 中文列名），顺序即 Excel 列顺序 |
| `specs()` | 该族全部任务（每次重新构造：模型路径来自 `.env`，测试可能临时改配置）|
| `compute_metrics(data, unit, scale)` | 指标算法，返回 `{列 key: 数值}` |

`TaskSpec` 里的字段（`preserve_mask_topology`、`validate_side_bundles`、`retina_masks`、
`smooth`、`iou` …）就是两族"后处理不一样"的全部载体，由共享的
`infrastructure/inference/runner.py` 消费 —— 它不认识族名，只认这些开关。

## 改动落在哪

| 想做什么 | 改哪里 |
|---|---|
| 加/换一个模型权重 | `features/task_catalog/families/<族>.py` 的 `specs()` |
| 改导出列（增删/改名/调顺序） | 同上文件的 `COLUMNS` |
| 改后处理/推理参数 | 同上文件的 `specs()` / `*_TASK_DEFAULTS` |
| 改指标算法 | `domain/analysis/families/<族>.py` 的 `compute()` |
| 改共享几何/单位换算 | `domain/analysis/metrics_common.py`（**两族都受影响，改前确认**）|

前端导出的列由后端下发的 `columns_for()` 决定，**改列不需要动前端**。

## 加第三个大类（例如「根系」）

1. 建 `domain/analysis/families/root.py`，实现 `compute(data, unit, scale) -> dict`
2. 建 `features/task_catalog/families/root.py`，导出 `FAMILY = TaskFamily(...)`
3. 在 `features/task_catalog/families/__init__.py` 的 `ALL_FAMILIES` 里加一项
4. （前端要独立页面时）加一个新页面挂 `<AnalysisWorkspace group="root" />`

**共享核心一行都不用改** —— 这条由测试守着，见下。

## 边界规则（有测试强制）

`tests/unit/test_family_boundaries.py` 守住四件事：

1. **共享核心里不出现具体族名**（AST 扫字符串字面量）。共享核心 = `types.py`、
   `registry.py`、`export/excel.py`、`export/service.py`、`history_service.py`、
   `statistics_service.py`、`metrics_common.py`。
2. **共享核心不直接 import 具体族**。唯一例外是 `registry.py` 聚合
   `families/__init__.py` 的 `ALL_FAMILIES`（这正是注册表的职责）。
3. **列的 key 与算法产出的 key 必须对得上** —— 防止"加了指标忘了加列"（导出会静默变 N/A）。
4. **用临时假族证明可扩展**：注册进去之后 `get_tasks` / `family_of` / `columns_for` /
   `compute_metrics` / `list_tasks` / `list_models` 全都认得它。

改动族相关代码后跑：

```powershell
D:\Anaconda\envs\fastapi\python.exe -B -m unittest tests.unit.test_family_boundaries -v
```

## 不变量（别动）

* `task_type`（数据库历史数据）与 `group`（前端 API 契约）的字符串值
* `TaskSpec.metrics` 是**已废弃别名**（等于 `group`），只为历史快照与仓库外旧脚本保留；
  确认无引用后可删
* 指标口径本身：`tests/e2e/verify_refactor.py` 会拿 2026-09-22 的基线快照逐值比对
  （18 组用例 + 真实剑叶结果）。**重构期间它必须一直是绿的**。
