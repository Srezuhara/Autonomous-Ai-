"""Entry module: importing it must pull in the router and its service."""
import sys as _sys, os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
_parent = _os.path.dirname(_here)
for _p in [_here, _parent]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from routers.warehouse import warehouse_stock

RESULT = warehouse_stock(1)
