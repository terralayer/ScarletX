from __future__ import annotations

# Compatibility facade: callers importing scarletx.main receive the relocated
# application module itself, so monkeypatching and private compatibility imports
# continue to operate on the implementation globals.
import sys as _sys
from .routes import application as _application

_parent = _sys.modules.get(__package__)
if _parent is not None:
    setattr(_parent, 'main', _application)
_sys.modules[__name__] = _application
