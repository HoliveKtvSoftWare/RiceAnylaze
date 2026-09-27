"""Compatibility alias for app.features.export.excel; mutable state is shared."""

import sys
from app.features.export import excel as _implementation

sys.modules[__name__] = _implementation
