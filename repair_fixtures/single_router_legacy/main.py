from fastapi import FastAPI

from routes import weather_router

app = FastAPI()

app.include_router(weather_router)
