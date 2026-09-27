"""Compatibility alias for app.api.routers.export; mutable module state is shared."""

import sys
from app.api.routers import export as _implementation

sys.modules[__name__] = _implementation
