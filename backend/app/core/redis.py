"""Async Redis client dependency and graceful health check."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from redis.asyncio import Redis, from_url

from app.core.config import get_settings


def create_redis_client(socket_timeout: float = 2.0) -> Redis:
    """Create an async Redis client bound to `settings.REDIS_URL`."""
    settings = get_settings()
    return from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=socket_timeout,
        socket_timeout=socket_timeout,
    )


async def _close_redis_client(client: Redis) -> None:
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        await aclose()
    else:
        await client.close()


async def get_redis() -> AsyncIterator[Redis]:
    """FastAPI dependency yielding an async Redis client and closing it afterward."""
    client = create_redis_client()
    try:
        yield client
    finally:
        with suppress(Exception):
            await _close_redis_client(client)


async def check_redis_health(timeout_seconds: float = 2.0) -> bool:
    """Return True if Redis responds to PING, or False on any connection/timeout error."""
    client: Redis | None = None
    try:
        client = create_redis_client(socket_timeout=timeout_seconds)
        pong: object = await asyncio.wait_for(client.ping(), timeout=timeout_seconds)
        return bool(pong)
    except Exception:
        return False
    finally:
        if client is not None:
            with suppress(Exception):
                await _close_redis_client(client)
