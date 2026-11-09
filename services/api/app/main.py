import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, cart, catalog, health, products, sessions, tryon, uploads
from app.core.config import settings
from app.core.logging import RequestLoggingMiddleware, configure_logging

configure_logging(settings.log_level)
logger = logging.getLogger("app")

app = FastAPI(
    title="AI Try-On API",
    version="0.1.0",
    description="Backend for the virtual try-on mirror: catalog, sessions, carts and try-on jobs.",
)

# CORS: only the configured browser origins (the kiosk, plus the admin app) may call the API.
# No cookies are used, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
# Added last so it is outermost and sees every request, including CORS preflights.
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(products.router)
app.include_router(sessions.router)
app.include_router(cart.router)
app.include_router(uploads.router)
app.include_router(tryon.router)
app.include_router(admin.router)

logger.info("api_started", extra={"cors_origins": settings.cors_origins})
