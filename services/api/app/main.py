import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, health, products, sessions, tryon, uploads
from app.core.config import settings

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="AI Try-On API",
    version="0.1.0",
    description="Backend for the virtual try-on mirror: catalog, sessions, uploads and try-on jobs.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(products.router)
app.include_router(sessions.router)
app.include_router(uploads.router)
app.include_router(tryon.router)
app.include_router(admin.router)
