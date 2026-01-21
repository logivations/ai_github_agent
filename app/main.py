from fastapi import FastAPI
from app.webhook import router

app = FastAPI()
app.include_router(router)
