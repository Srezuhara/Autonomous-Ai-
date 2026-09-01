from fastapi import APIRouter

weather_router = APIRouter()


@weather_router.get("/weather")
def forecast():
    return {}
