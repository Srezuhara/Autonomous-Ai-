"""A service module one package away from the router that uses it."""


def get_stock_levels(warehouse_id: int) -> dict:
    return {"warehouse_id": warehouse_id, "levels": []}
