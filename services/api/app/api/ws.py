"""WebSocket endpoint: live job events for one session.

    ws://host/ws?session={session_id}

On connect the server subscribes to the Redis pattern `session:{id}:*` and forwards every message to the
socket as-is (currently JSON like {"job": ..., "status": "processing", "pct": 40}). It also sends
`{"type": "ping"}` every 25 seconds so idle connections stay open through proxies and so a browser, which
cannot see WebSocket ping frames, can tell the server is alive. Messages from the client are ignored.

Pub/sub has no history. A client that (re)connects should read `GET /jobs/{id}` once for the current state
and treat the socket as updates after that. The subscription is live before the handshake completes, so
anything published after the connection opens is delivered.
"""

import asyncio
import contextlib
import hmac
import json
import logging
import time
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError

from app.core.config import settings

router = APIRouter(tags=["realtime"])
logger = logging.getLogger("app.ws")

HEARTBEAT = json.dumps({"type": "ping"})


async def _subscribe(pubsub: aioredis.client.PubSub, pattern: str) -> None:
    """Subscribe and wait for Redis to confirm, so the subscription is really active on return."""
    await pubsub.psubscribe(pattern)
    async with asyncio.timeout(settings.ws_subscribe_timeout_seconds):
        while True:
            message = await pubsub.get_message(timeout=1.0)
            if message and message["type"] == "psubscribe":
                return


async def _release(pubsub: aioredis.client.PubSub, conn: aioredis.Redis, pattern: str) -> None:
    """Unsubscribe and close the Redis connection. Each step is attempted even if one fails."""
    for step in (lambda: pubsub.punsubscribe(pattern), pubsub.aclose, conn.aclose):
        try:
            await step()
        except Exception:
            logger.debug("ws_release_step_failed", exc_info=True)


@router.websocket("/ws")
async def session_events(websocket: WebSocket, session: uuid.UUID):
    # `session` is typed as a UUID on purpose: a free-form value could contain glob characters (`*`)
    # and subscribe to every session's events. A malformed value is refused before the handshake.
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        # Browsers do not apply CORS to WebSockets, so enforce the same allow-list here.
        logger.warning("ws_origin_rejected", extra={"origin": origin})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    pattern = f"session:{session}:*"
    conn = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = conn.pubsub()
    try:
        await _subscribe(pubsub, pattern)
    except (RedisError, OSError, TimeoutError):
        logger.exception("ws_subscribe_failed", extra={"session_id": str(session)})
        await _release(pubsub, conn, pattern)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)  # refused: the client falls back to polling
        return

    await websocket.accept()
    await _pump(websocket, pubsub, conn, pattern, {"session_id": str(session)})


async def _pump(
    websocket: WebSocket,
    pubsub: aioredis.client.PubSub,
    conn: aioredis.Redis,
    pattern: str,
    log_extra: dict,
) -> None:
    """Forward the subscription to an accepted socket until either side goes, then clean everything up."""
    started = time.monotonic()
    forwarded = 0
    send_lock = asyncio.Lock()  # the forwarder and the heartbeat share one socket
    logger.info("ws_connected", extra=log_extra)

    async def send(text: str) -> None:
        async with send_lock:
            await websocket.send_text(text)

    async def forward() -> None:
        nonlocal forwarded
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                await send(message["data"])
                forwarded += 1

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(settings.ws_heartbeat_seconds)
            await send(HEARTBEAT)

    async def watch_client() -> None:
        # Nothing is expected from the client, but reading is how a disconnect is noticed promptly.
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass

    tasks = [asyncio.create_task(c, name=c.__name__) for c in (forward(), heartbeat(), watch_client())]
    close_code = status.WS_1000_NORMAL_CLOSURE
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled() and isinstance(task.exception(), RedisError):
                logger.error("ws_redis_failed", extra=log_extra, exc_info=task.exception())
                close_code = status.WS_1011_INTERNAL_ERROR  # ask the client to reconnect
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _release(pubsub, conn, pattern)
        with contextlib.suppress(Exception):  # already closed if the client left first
            await websocket.close(code=close_code)
        logger.info(
            "ws_disconnected",
            extra={**log_extra, "forwarded": forwarded, "seconds": round(time.monotonic() - started, 1)},
        )


STAFF_CHANNEL = "staff:requests"
STAFF_AUTH_TIMEOUT_SECONDS = 5.0


@router.websocket("/ws/staff")
async def staff_events(websocket: WebSocket):
    """Live "Request Outfit" events for the staff page, over the same machinery as `/ws`.

    A browser cannot set headers on a WebSocket and a key in the URL would end up in logs, so the client sends
    `{"type": "auth", "key": "<staff key>"}` as its first message. The server then subscribes and answers
    `{"type": "ready"}`; only after that should the client read `GET /requests`, so no change can fall
    between the
    list and the stream. Events are `{"type": "request.created" | "request.updated", "request": {...}}`.
    """
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        logger.warning("ws_origin_rejected", extra={"origin": origin})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    try:
        first = json.loads(await asyncio.wait_for(websocket.receive_text(), STAFF_AUTH_TIMEOUT_SECONDS))
        key = first.get("key") if isinstance(first, dict) and first.get("type") == "auth" else None
    except (TimeoutError, ValueError, WebSocketDisconnect):
        key = None
    if not isinstance(key, str) or not _staff_key_ok(key):
        with contextlib.suppress(Exception):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    conn = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = conn.pubsub()
    try:
        await _subscribe(pubsub, STAFF_CHANNEL)
    except (RedisError, OSError, TimeoutError):
        logger.exception("ws_staff_subscribe_failed")
        await _release(pubsub, conn, STAFF_CHANNEL)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    await websocket.send_text(json.dumps({"type": "ready"}))
    await _pump(websocket, pubsub, conn, STAFF_CHANNEL, {"channel": "staff"})


def _staff_key_ok(key: str) -> bool:
    return any(
        hmac.compare_digest(key, expected) for expected in (settings.staff_api_key, settings.admin_api_key)
    )
