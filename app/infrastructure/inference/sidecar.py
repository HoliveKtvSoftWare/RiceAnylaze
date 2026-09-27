"""File-protocol adapter for running forked ultralytics in a subprocess.

This module deliberately has no dependency on application settings, database,
or ORM packages. Runtime paths can be supplied through environment variables
(``FORK_PYTHON``, ``SIDECAR_SCRIPT``, ``FORK_PYLIBS``, ``RICE_FORK_PROJECT``).
"""

import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[3]


def _task_spec(task):
    return {
        "key": task.key,
        "name": task.name,
        "model_path": task.model_path,
        "colors": {key: list(value) for key, value in task.colors.items()},
        "draw_first": list(task.draw_first),
        "outline_labels": list(task.outline_labels),
        "smooth": task.smooth,
        "smooth_exclude": list(task.smooth_exclude),
        "preview_smooth": task.preview_smooth,
        "preserve_mask_topology": task.preserve_mask_topology,
        "validate_side_bundles": task.validate_side_bundles,
        "embed_image": task.embed_image,
        "predict_imgsz": task.predict_imgsz,
        "conf": task.conf,
        "iou": task.iou,
        "retina_masks": task.retina_masks,
    }


def run_via_sidecar(task, image_path: str, output_dir: str, basename: str, *,
                    fork_python=None, script=None, fork_pylibs=None, fork_project=None):
    """Run the isolated sidecar using explicit settings or environment defaults."""
    result_json = os.path.join(output_dir, f"_sidecar_{task.key}.json")
    log_path = os.path.join(output_dir, f"_sidecar_{task.key}.log")
    spec_path = os.path.join(output_dir, f"_sidecar_{task.key}_spec.json")
    for path in (result_json, log_path, spec_path):
        if os.path.exists(path):
            os.remove(path)
    with open(spec_path, "w", encoding="utf-8") as handle:
        json.dump(_task_spec(task), handle, ensure_ascii=False, indent=2)

    fork_python = fork_python or os.environ.get("FORK_PYTHON", r"D:\Anaconda\envs\yolo\python.exe")
    script = script or os.environ.get("SIDECAR_SCRIPT", str(BACKEND_DIR / "deploy" / "runtime" / "sidecar_infer.py"))
    fork_pylibs = fork_pylibs or os.environ.get("FORK_PYLIBS", str(BACKEND_DIR / ".pylibs"))
    fork_project = fork_project or os.environ.get("RICE_FORK_PROJECT", str(BACKEND_DIR / ".ultra_refine"))
    cmd = [fork_python, script, "--spec", spec_path, "--image", image_path,
           "--out-dir", output_dir, "--basename", basename, "--result-json", result_json]
    env = os.environ.copy()
    env["PYTHONPATH"] = fork_pylibs + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["RICE_FORK_PROJECT"] = fork_project
    log.info("sidecar: %s -> %s", task.key, fork_python)
    with open(log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT,
                              env=env, timeout=3600)
    if not os.path.exists(result_json):
        raise RuntimeError(f"sidecar did not produce result file (exit {proc.returncode}); log: {log_path}")
    with open(result_json, encoding="utf-8") as handle:
        data = json.load(handle)
    if not data.get("ok"):
        raise RuntimeError(f"sidecar failed: {data.get('error')}; log: {log_path}")
    return data["annotated_image_path"], data["result_json_path"]
