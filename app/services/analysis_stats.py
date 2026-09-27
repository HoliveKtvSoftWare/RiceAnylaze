"""Compatibility alias for app.features.analysis.statistics_service; mutable state is shared."""

import sys
from app.features.analysis import statistics_service as _implementation

sys.modules[__name__] = _implementation
