"""Compatibility entry; implementation is in deploy/experiments."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(
    str(Path(__file__).resolve().parent / "experiments" / "test_sidecar.py"),
    run_name=__name__,
))
