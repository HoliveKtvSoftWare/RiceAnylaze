"""Compatibility entry; implementation is in deploy/runtime."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(
    str(Path(__file__).resolve().parent / "runtime" / "sidecar_infer.py"),
    run_name=__name__,
))
