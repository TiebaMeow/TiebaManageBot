from __future__ import annotations

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

_redis_pool: ConnectionPool | None = None
_redis_client: Redis | None = None


def init_redis_pool(url: str, decode_responses: bool = True) -> None:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = ConnectionPool.from_url(
            url,
            decode_responses=decode_responses,
            max_connections=20,
        )


async def close_redis_pool() -> None:
    global _redis_pool, _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


def get_redis() -> Redis:
    global _redis_pool, _redis_client
    if _redis_pool is None:
        raise RuntimeError("Redis pool not initialized. Call init_redis_pool first.")
    if _redis_client is None:
        _redis_client = Redis(connection_pool=_redis_pool)
    return _redis_client
