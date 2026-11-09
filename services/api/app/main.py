import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    capture,
    cart,
    catalog,
    health,
    jobs,
    orders,
    products,
    recommend,
    sessions,
    share,
    staff,
    tryon,
    uploads,
    ws,
)
from app.core.config import settings
from app.core.limits import BodySizeLimitMiddleware
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.services.capture_cleanup import cleanup_loop

configure_logging(settings.log_level)
logger = logging.getLogger("app")

# Multipart framing on top of the file itself.
CAPTURE_BODY_LIMIT = settings.capture_max_bytes + 64 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    sweeper = None
    if settings.capture_cleanup_enabled:
        sweeper = asyncio.create_task(cleanup_loop(settings.capture_cleanup_interval_seconds))
    try:
        yield
    finally:
        if sweeper:
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper


app = FastAPI(
    lifespan=lifespan,
    title="AI Try-On API",
    version="0.1.0",
    description="Backend for the virtual try-on mirror: catalog, sessions, carts and try-on jobs.",
)

# Innermost of the three, so an over-size 413 still gets CORS headers and a request-log line.
app.add_middleware(BodySizeLimitMiddleware, limits={"/capture": CAPTURE_BODY_LIMIT})

# CORS: only the configured browser origins (the kiosk, plus the admin app) may call the API.
# No cookies are used, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key", "X-Staff-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
# Added last so it is outermost and sees every request, including CORS preflights.
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(products.router)
app.include_router(recommend.router)
app.include_router(sessions.router)
app.include_router(cart.router)
app.include_router(share.router)
app.include_router(staff.router)
app.include_router(orders.router)
app.include_router(capture.router)
app.include_router(uploads.router)
app.include_router(tryon.router)
app.include_router(jobs.router)
app.include_router(ws.router)
app.include_router(admin.router)

logger.info("api_started", extra={"cors_origins": settings.cors_origins})
