"""Compatibility alias for app.api.routers.excel; mutable module state is shared."""

import sys
from app.api.routers import excel as _implementation

sys.modules[__name__] = _implementation
