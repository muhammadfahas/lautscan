"""Async Redis client dependency and graceful health check."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import cast

from redis.asyncio import Redis, from_url

from app.core.config import get_settings

_REDIS_COOLDOWN_SECONDS = 15.0
_redis_unavailable_until = 0.0


def create_redis_client(socket_timeout: float = 0.4) -> Redis:
    """Create an async Redis client bound to `settings.REDIS_URL`."""
    settings = get_settings()
    return cast(
        Redis,
        from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=socket_timeout,
            socket_timeout=socket_timeout,
        ),
    )


async def _close_redis_client(client: Redis) -> None:
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        await aclose()
    else:
        await client.close()


async def get_redis() -> AsyncIterator[Redis | None]:
    """FastAPI dependency yielding an async Redis client (or `None` during cooldown)."""
    global _redis_unavailable_until
    if time.monotonic() < _redis_unavailable_until:
        yield None
        return

    client = create_redis_client(socket_timeout=0.4)
    try:
        try:
            await asyncio.wait_for(client.ping(), timeout=0.4)
            _redis_unavailable_until = 0.0
        except Exception:
            _redis_unavailable_until = time.monotonic() + _REDIS_COOLDOWN_SECONDS
            yield None
            return
        yield client
    finally:
        with suppress(Exception):
            await _close_redis_client(client)


async def check_redis_health(timeout_seconds: float = 0.5) -> bool:
    """Return True if Redis responds to PING, or False on any connection/timeout error."""
    global _redis_unavailable_until
    client: Redis | None = None
    try:
        client = create_redis_client(socket_timeout=timeout_seconds)
        pong: object = await asyncio.wait_for(client.ping(), timeout=timeout_seconds)
        ok = bool(pong)
        _redis_unavailable_until = 0.0 if ok else time.monotonic() + _REDIS_COOLDOWN_SECONDS
        return ok
    except Exception:
        _redis_unavailable_until = time.monotonic() + _REDIS_COOLDOWN_SECONDS
        return False
    finally:
        if client is not None:
            with suppress(Exception):
                await _close_redis_client(client)
