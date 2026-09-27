"""Compatibility entry; implementation is in deploy/maintenance."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(
    str(Path(__file__).resolve().parent / "maintenance" / "cleanup_test_account.py"),
    run_name=__name__,
))
