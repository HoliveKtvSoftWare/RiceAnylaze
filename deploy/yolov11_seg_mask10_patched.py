"""Compatibility entry; implementation is in deploy/experiments."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(
    str(Path(__file__).resolve().parent / "experiments" / "yolov11_seg_mask10_patched.py"),
    run_name=__name__,
))
