"""Compatibility alias for app.infrastructure.storage.previews; mutable state is shared."""

import sys
from app.infrastructure.storage import previews as _implementation

sys.modules[__name__] = _implementation
