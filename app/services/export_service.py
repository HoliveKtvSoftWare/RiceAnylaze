"""Compatibility alias for app.features.export.service; mutable module state is shared."""

import sys
from app.features.export import service as _implementation

sys.modules[__name__] = _implementation
