# Inference Refactor Report

## Scope

This change separates inference concerns while preserving the legacy import paths and call signatures. The implementation is Python 3.8 compatible and does not perform database writes.

## Implemented

- `app/infrastructure/inference/native.py` owns ultralytics model loading and prediction keyword construction.
- `app/infrastructure/inference/labelme.py` owns base64 embedding, polygon smoothing, preview simplification, and LabelMe conversion.
- `app/infrastructure/inference/renderer.py` owns PIL polygon rendering and preview-only smoothing.
- `app/infrastructure/inference/runner.py` owns the native end-to-end `run_system` pipeline, including topology preservation, side-bundle reassignment, JSON/JPG naming, and output writing.
- `app/infrastructure/inference/sidecar.py` owns the file-protocol subprocess adapter `run_via_sidecar(task, image_path, output_dir, basename)`. It has no settings, database, or ORM import and preserves the 3600-second timeout, spec/result files, environment variables, and error behavior.
- `app/domain/geometry/mask_geometry.py` is the relocated topology implementation; `app/services/mask_geometry.py` is a compatibility export.
- `app/features/task_catalog/types.py` contains `TaskSpec` and rendering defaults; `catalog.py` contains the settings-backed registry and queries; `app/core/tasks.py` remains a compatibility export.
- `app/services/yolo_inference.py` remains importable and re-exports the old public helpers, including `run_system`.

The sidecar deploy entry point should resolve the backend root on `sys.path` and import `app.infrastructure.inference.runner.run_system`. It must continue to insert the fork runtime before the backend path so forked ultralytics wins for fork tasks. The parent agent has updated the deploy wrapper/runtime path accordingly.

## Parent integration verification

The baseline archive and migrated pipeline produced identical LabelMe JSON and preview JPG files on the real TIFF fixture for both `leaf` native inference (161 shapes) and `leaf_our` fork inference (206 shapes). The fork run reported `mask_refine=true`.

## Verification

Executed with `D:\Anaconda\envs\fastapi\python.exe -B`:

- `test_inference_refactor.py`: 6 passed.
- `test_mask_geometry.py`: 7 passed.
- `test_leaf_task_config.py`: 2 passed.
- `test_task_groups.py`: 15 passed.
- `test_leaf_metrics.py`: 1 passed.
- `compileall` passed for all new inference/domain/catalog modules.
- Importing `app.infrastructure.inference.sidecar` leaves `app.core.config`, `app.database`, `sqlmodel`, `ultralytics`, and `torch` unloaded.

The focused tests cover LabelMe topology output, preview rendering compatibility, task defaults/groups, legacy aliases, native predict arguments, and sidecar success/error protocol handling. Real native/fork model output comparison is intentionally left to the parent integration run because it requires the installed model weights and fork runtime.

## Compatibility Notes

- `catalog.py` still reads `app.core.config.settings` for model paths, matching the previous registry behavior. The pure sidecar adapter itself does not read settings; runtime paths are supplied via environment variables with the same defaults as the prior service.
- The old `app.services.yolo_inference.run_system` import remains valid and delegates to the new runner.
- Generated preview and LabelMe filenames remain `<basename>.jpg` and `<basename>.json`; sidecar bookkeeping files retain their `_sidecar_<task>` names.
