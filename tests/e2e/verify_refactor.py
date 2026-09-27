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
from openpyxl import load_workbook


def verify():
    old_api = json.loads((ROOT / ".run/openapi-before.json").read_text(encoding="utf-8"))
    assert app.openapi() == old_api, "OpenAPI contract changed"
    with zipfile.ZipFile(ROOT / ".run/architecture-baseline-20260922.zip") as archive:
        baseline = types.ModuleType("baseline_excel")
        source = archive.read("app/services/excel_download.py").decode("utf-8-sig")
        exec(compile(source, "baseline_excel.py", "exec"), baseline.__dict__)
    old, new = baseline.ExcelDownloadService(), ExcelDownloadService()
    assert old.stem_columns == new.stem_columns
    assert old.leaf_columns == new.leaf_columns
    data = {"shapes": [
        {"label": label, "points": [[0, 0], [8, 0], [8, 4], [0, 4]], "flags": {}}
        for label in ["big", "small", "in", "out", "body1", "body2", "side1", "side2",
                      "body_big", "body1_small", "side1_small"]
    ]}
    cases = 0
    for task in ("stem", "leaf"):
        for unit in ("um", "mm", "cm"):
            for scale in (1, 2.5, 500):
                method = "_load_" + task + "_metrics"
                a, b = getattr(old, method)(data, unit, scale), getattr(new, method)(data, unit, scale)
                assert a == b, (task, unit, scale)
                columns = list(old.get_available_columns(task))
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
            assert old._load_leaf_metrics(result, "um", 2.5) == new._load_leaf_metrics(result, "um", 2.5)

    # Infrastructure and domain should not depend back on compatibility modules.
    violations = []
    for folder in ("features", "infrastructure", "domain", "api/routers"):
        for path in (ROOT / "app" / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(("app.services", "app.database", "app.api.endpoints", "app.core.tasks")):
                        violations.append(str(path.relative_to(ROOT)) + ": " + node.module)
    assert not violations, violations
    report = {"openapi_identical": True, "paths": len(old_api["paths"]),
              "metric_and_workbook_cases": cases, "real_leaf_metrics_identical": True,
              "legacy_dependency_violations": violations}
    (ROOT / ".run/refactor-contract-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    verify()
