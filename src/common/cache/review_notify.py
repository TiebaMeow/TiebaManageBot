from pathlib import Path
from typing import Any

from cashews import Cache

CACHE_DIR = Path(__file__).parents[3] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

review_notify_cache = Cache()
review_notify_cache.setup(f"disk://?directory={(CACHE_DIR / 'review_notify_cache').as_posix()}&shards=0")


async def get_review_notify_payload(message_id: int) -> dict[str, Any] | None:
    key = f"msg:{message_id}"
    payload = await review_notify_cache.get(key)
    if not payload:
        return None
    return payload


async def set_review_notify_payload(message_id: int, payload: dict[str, Any]) -> None:
    key = f"msg:{message_id}"
    await review_notify_cache.set(key, payload, expire="2d")
