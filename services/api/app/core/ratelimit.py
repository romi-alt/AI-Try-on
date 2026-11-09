"""Rate limiting for the public API: a fixed window per key, counted in Redis.

Every rule is "at most `limit` hits per `window` seconds for one key". The key is the shopper's *session*
wherever the request carries one (so one mirror's shoppers do not slow each other down, and a runaway client
cannot spend the GPU budget), and the client's address where it does not (starting a session, guessing
mobile-page codes, guessing admin keys).

- It is a fixed window, not a sliding one: a client can use up one window's allowance at its very end and the
  next window's at its very start, so the real burst ceiling is twice the limit. That is fine for what this
  protects.
- Redis keys carry a hash of the address, never the address itself, and expire with their window.
- If Redis is unreachable the request is let through (`RATE_LIMIT_FAIL_OPEN`, default on): a shop that cannot
  limit is better than a shop that cannot sell. The failure is logged.
- Behind a reverse proxy the address is the proxy's unless uvicorn runs with `--proxy-headers` and
  `--forwarded-allow-ips` set to the proxy (the production compose file does this). Never publish the API port
  directly in that setup, or a client could forge the header.
"""

import hashlib
import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from app.core.config import settings
from app.core.redis import get_redis

logger = logging.getLogger("app.ratelimit")


@dataclass(frozen=True)
class Rule:
    limit: int
    window: int  # seconds


# name -> rule. The names show up in 429 logs. `_session` rules key on the session id, `_ip` on the address.
RULES: dict[str, Rule] = {
    "session_start_ip": Rule(30, 60),  # a mirror starts a session per shopper; 30 a minute is a busy shop
    "capture_session": Rule(10, 60),
    "capture_ip": Rule(60, 60),
    "tryon_session": Rule(12, 600),  # each try-on can cost GPU money: about one a minute, with room to burst
    "tryon_ip": Rule(120, 600),
    "cart_session": Rule(60, 60),
    "share_session": Rule(10, 60),
    "request_outfit_session": Rule(10, 60),  # staff are paged for each one
    "checkout_session": Rule(10, 60),
    "mobile_page_ip": Rule(120, 60),
    "mobile_bad_code_ip": Rule(20, 600),  # unknown or expired codes: someone is guessing
    "mobile_checkout_code": Rule(10, 600),
    "mobile_checkout_ip": Rule(30, 600),
    "ws_connect_ip": Rule(60, 60),
    "bad_key_ip": Rule(10, 300),  # wrong admin or staff key
}

_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if count == 1 or ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


def client_ip(request: HTTPConnection | None) -> str:
    client = getattr(request, "client", None)
    return client.host if client else "unknown"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _scaled(rule: Rule) -> int:
    return max(1, round(rule.limit * settings.rate_limit_scale))


def _hit(name: str, key: str) -> tuple[int, int]:
    """Count one hit and return `(count so far in this window, seconds until the window ends)`."""
    rule = RULES[name]
    redis_key = f"{settings.rate_limit_prefix}:{name}:{key}"
    script = get_redis().register_script(_SCRIPT)
    count, ttl = script(keys=[redis_key], args=[rule.window])
    return int(count), max(1, int(ttl))


async def check(name: str, key: object, *, ip: bool = False) -> None:
    """Count a hit for `name` and raise 429 if the key is over its limit. `ip=True` hashes the key first."""
    if not settings.rate_limit_enabled:
        return
    k = _hash(str(key)) if ip else str(key)
    try:
        count, ttl = await run_in_threadpool(_hit, name, k)
    except Exception:
        logger.warning("rate_limit_unavailable", extra={"rule": name}, exc_info=True)
        if settings.rate_limit_fail_open:
            return
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Please try again in a moment.") from None
    if count > _scaled(RULES[name]):
        logger.warning("rate_limited", extra={"rule": name, "retry_after": ttl})
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many requests. Please wait {ttl} seconds and try again.",
            headers={"Retry-After": str(ttl)},
        )


async def check_session(name: str, session_id: object) -> None:
    await check(name, session_id)


async def check_ip(name: str, request: HTTPConnection | None) -> None:
    await check(name, client_ip(request), ip=True)


def peek_blocked(name: str, key: str) -> int:
    """Seconds left if the (hashed) `key` is already over `name`'s limit, without counting a hit; else 0.

    For failure counters: check this before an attempt, and call `record_failure` when it fails.
    """
    if not settings.rate_limit_enabled:
        return 0
    redis_key = f"{settings.rate_limit_prefix}:{name}:{_hash(key)}"
    try:
        raw = get_redis().get(redis_key)
        if raw is not None and int(raw) >= _scaled(RULES[name]):
            return max(1, get_redis().ttl(redis_key))
    except Exception:
        logger.warning("rate_limit_unavailable", extra={"rule": name}, exc_info=True)
    return 0


def record_failure(name: str, key: str) -> None:
    if not settings.rate_limit_enabled:
        return
    try:
        _hit(name, _hash(key))
    except Exception:
        logger.warning("rate_limit_unavailable", extra={"rule": name}, exc_info=True)


def too_many(seconds: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"Too many attempts. Please wait {seconds} seconds and try again.",
        headers={"Retry-After": str(seconds)},
    )


async def raise_if_blocked(name: str, request: HTTPConnection | None) -> None:
    if seconds := await run_in_threadpool(peek_blocked, name, client_ip(request)):
        logger.warning("rate_limited", extra={"rule": name, "retry_after": seconds})
        raise too_many(seconds)


async def record_ip_failure(name: str, request: HTTPConnection | None) -> None:
    await run_in_threadpool(record_failure, name, client_ip(request))
