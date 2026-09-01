from fastapi import APIRouter

router = APIRouter()


@router.get("/warehouses")
def list_warehouses():
    return []
