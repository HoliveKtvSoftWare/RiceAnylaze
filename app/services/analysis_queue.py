"""Compatibility alias for app.features.analysis.queue; mutable state is shared."""

import sys
from app.features.analysis import queue as _implementation

sys.modules[__name__] = _implementation
