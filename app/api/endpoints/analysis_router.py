"""Compatibility alias for app.api.routers.analysis; mutable module state is shared."""

import sys
from app.api.routers import analysis as _implementation

sys.modules[__name__] = _implementation
