from fastapi import APIRouter

router = APIRouter()


@router.get("/products")
def list_products():
    return []
