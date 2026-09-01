from fastapi import APIRouter

router = APIRouter()


@router.get("/suppliers")
def list_suppliers():
    return []
