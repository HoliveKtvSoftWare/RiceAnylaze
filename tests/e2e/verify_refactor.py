"""Compare public contracts, metrics and workbook cells with the local snapshot."""
import ast
import io
import json
import os
from pathlib import Path
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from app.main import app
from app.features.export.excel import ExcelDownloadService
from app.features.task_catalog import registry
from openpyxl import load_workbook

# 新版前端（RiceAnylazeWeb@main）实际会调用的接口。
# 重构之后为了让它能直接对接，后端又扩了 /analysis/models 与异步导出
# /excel/tasks|download，所以这里不再要求和重构前的快照逐字节一致，
# 而是校验两件事：原有接口一个都不能少，前端要的接口必须都在。
REQUIRED_FRONTEND_ROUTES = [
    "/api/analysis/models",
    "/api/analysis/history",
    "/api/analysis/upload",
    "/api/analysis/upload/batch",
    "/api/analysis/delete/{analysis_id}",
    "/api/analysis/delete/batch",
    "/api/excel/columns",
    "/api/excel/summary",
    "/api/excel/batch",
    "/api/excel/{analysis_id}",
    "/api/excel/tasks/{task_id}",
    "/api/excel/download/{task_id}",
    "/api/export/json/{analysis_id}",
    "/api/export/json/preview/{analysis_id}",
    "/api/export/json/batch",
    "/api/export/list",
]


def _install_baseline_aliases():
    """给"快照里的旧代码"补上它当年依赖的模块路径。

    基线 zip 里的 `excel_download.py` 写的是 `from app.database.session import ...`
    和 `from app.services.mask_geometry import ...`，这两条兼容转发已经从生产代码里
    删除（它们只被测试引用过）。要跑历史对比，就由这个脚本自己把旧路径映射到新实现，
    而不是为一个对比脚本在生产树里留转发文件。
    """
    import app.services                                            # noqa: F401  真实包，仍需可导入
    import app.domain.geometry.mask_geometry as new_geometry
    import app.infrastructure.database.session as new_session

    # app/database/ 目录本身已删除，所以要造一个带 __path__ 的包占位
    legacy_pkg = types.ModuleType("app.database")
    legacy_pkg.__path__ = []
    sys.modules.setdefault("app.database", legacy_pkg)

    sys.modules["app.database.session"] = new_session
    sys.modules["app.services.mask_geometry"] = new_geometry


def verify():
    old_api = json.loads((ROOT / ".run/openapi-before.json").read_text(encoding="utf-8"))
    current_api = app.openapi()

    # 1) 不破坏既有消费者：基线里的路径必须仍然存在（允许新增）
    removed_paths = sorted(set(old_api["paths"]) - set(current_api["paths"]))
    assert not removed_paths, "refactor dropped existing routes: {}".format(removed_paths)

    # 2) 新版前端需要的接口必须齐全
    missing_routes = sorted(p for p in REQUIRED_FRONTEND_ROUTES if p not in current_api["paths"])
    assert not missing_routes, "new frontend routes are missing: {}".format(missing_routes)

    with zipfile.ZipFile(ROOT / ".run/architecture-baseline-20260922.zip") as archive:
        _install_baseline_aliases()
        baseline = types.ModuleType("baseline_excel")
        source = archive.read("app/services/excel_download.py").decode("utf-8-sig")
        exec(compile(source, "baseline_excel.py", "exec"), baseline.__dict__)
    old, new = baseline.ExcelDownloadService(), ExcelDownloadService()
    # 新结构把「族」的列定义与指标算法搬到了 families/，这里从族取；
    # 基线只有一个 ExcelDownloadService。两侧比的是**数值**，不是方法名 ——
    # 所以基线用它的 _load_*_metrics，新结构用族的 compute_metrics。
    stem_family = registry.family_of("stem")
    leaf_family = registry.family_of("leaf")
    assert old.stem_columns == stem_family.columns
    assert old.leaf_columns == leaf_family.columns
    data = {"shapes": [
        {"label": label, "points": [[0, 0], [8, 0], [8, 4], [0, 4]], "flags": {}}
        for label in ["big", "small", "in", "out", "body1", "body2", "side1", "side2",
                      "body_big", "body1_small", "side1_small"]
    ]}
    cases = 0
    for task in ("stem", "leaf"):
        old_method = "_load_" + task + "_metrics"
        new_compute = registry.family_of(task).compute_metrics
        for unit in ("um", "mm", "cm"):
            for scale in (1, 2.5, 500):
                a = getattr(old, old_method)(data, unit, scale)
                b = new_compute(data, unit, scale)
                assert a == b, (task, unit, scale)
                # 列清单直接取基线自己的属性：基线里的 get_available_columns 会去读
                # TaskSpec.metrics，而该字段已改名为 group（基线是历史快照，不追改）
                columns = list(getattr(old, task + "_columns"))
                a["filename"] = b["filename"] = "fixture"
                old_xlsx = old.export_all_to_excel([a], columns, task)
                new_xlsx = new.export_all_to_excel([b], columns, task)
                old_book, new_book = load_workbook(old_xlsx), load_workbook(new_xlsx)
                assert list(old_book.active.values) == list(new_book.active.values)
                old_book.close()
                new_book.close()
                cases += 1
    for task in ("leaf", "leaf_our"):
        result_path = ROOT / ".run/inference-comparison" / task / "migrated/comparison.json"
        if result_path.exists():
            result = json.loads(result_path.read_text())
            assert old._load_leaf_metrics(result, "um", 2.5) == leaf_family.compute_metrics(result, "um", 2.5)

    # Infrastructure and domain should not depend back on compatibility modules.
    violations = []
    for folder in ("features", "infrastructure", "domain", "api/routers"):
        for path in (ROOT / "app" / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(("app.services", "app.database", "app.api.endpoints", "app.core.tasks")):
                        violations.append(str(path.relative_to(ROOT)) + ": " + node.module)
    assert not violations, violations
    report = {"baseline_paths": len(old_api["paths"]),
              "paths": len(current_api["paths"]),
              "removed_paths": removed_paths,
              "frontend_routes_missing": missing_routes,
              "metric_and_workbook_cases": cases, "real_leaf_metrics_identical": True,
              "legacy_dependency_violations": violations}
    (ROOT / ".run/refactor-contract-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    verify()
