"""Request body size limits enforced while the body streams in."""

from fastapi import HTTPException
from starlette.responses import JSONResponse


class BodySizeLimitMiddleware:
    """Reject over-long request bodies on selected paths with 413.

    Starlette spools a multipart upload to disk before the route runs, so a route-level size
    check alone would still let a client push gigabytes. This checks Content-Length up front and
    also counts bytes as they arrive (covering chunked uploads and lying headers).
    """

    def __init__(self, app, limits: dict[str, int]):
        self.app = app
        self.limits = limits

    async def __call__(self, scope, receive, send):
        limit = self.limits.get(scope.get("path")) if scope["type"] == "http" else None
        if limit is None or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        detail = f"Request body is larger than {limit} bytes."
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # An HTTPException is what FastAPI's body parsing lets through untouched.
                    raise HTTPException(413, detail)
            return message

        await self.app(scope, limited_receive, send)
