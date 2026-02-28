from typing import Any

from .disk_cache import disk_cache


async def get_review_notify_payload(message_id: int) -> dict[str, Any] | None:
    key = f"rn:msg:{message_id}"
    payload = await disk_cache.get(key)
    if not payload:
        return None
    return payload


async def set_review_notify_payload(message_id: int, payload: dict[str, Any]) -> None:
    key = f"rn:msg:{message_id}"
    await disk_cache.set(key, payload, expire="2d")
