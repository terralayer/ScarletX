from __future__ import annotations

# Compatibility alias: preserve the historical module object so tests, plugins,
# and callers that monkeypatch scarletx.native_usenet still patch worker globals.
import sys as _sys
from .usenet import worker as _worker

_parent = _sys.modules.get(__package__)
if _parent is not None:
    setattr(_parent, 'native_usenet', _worker)
_sys.modules[__name__] = _worker
