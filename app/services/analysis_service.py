"""Compatibility alias for app.features.analysis.service; mutable state is shared."""

import sys
from app.features.analysis import service as _implementation

sys.modules[__name__] = _implementation
