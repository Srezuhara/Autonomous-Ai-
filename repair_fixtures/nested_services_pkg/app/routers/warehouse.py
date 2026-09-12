"""The shape `_rewrite_dotted_imports` broke in inventory_system_1134f369.

`services` is a sibling PACKAGE of `routers`, reached through `app/` on the
path. Flattening `services.stock` to `stock` names a module no directory on
this file's path contains.
"""
import sys as _sys, os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
_parent = _os.path.dirname(_here)
for _p in [_here, _parent]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from services.stock import get_stock_levels


def warehouse_stock(warehouse_id: int) -> dict:
    return get_stock_levels(warehouse_id)
