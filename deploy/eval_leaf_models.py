"""Compatibility entry; implementation is in deploy/experiments."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(
    str(Path(__file__).resolve().parent / "experiments" / "eval_leaf_models.py"),
    run_name=__name__,
))
