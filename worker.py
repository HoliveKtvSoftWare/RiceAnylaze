"""Legacy RQ entry; the live application uses features.analysis.queue."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "deploy" / "legacy" / "worker.py"), run_name="__main__")
