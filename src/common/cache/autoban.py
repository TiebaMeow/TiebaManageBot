from __future__ import annotations

from datetime import datetime
from typing import Any

from tiebameow.utils.time_utils import SHANGHAI_TZ, now_with_tz

from .disk_cache import disk_cache


async def get_autoban_records(fid: int) -> list[dict[str, Any]]:
    key = f"autoban:fid:{fid}"
    records = await disk_cache.get(key)
    if records is None:
        records = []
        await disk_cache.set(key, records, expire="10d")
    return records


async def add_autoban_record(fid: int, count: int, at_time: datetime | None = None) -> None:
    if count <= 0:
        return
    if at_time is None:
        at_time = now_with_tz()
    elif at_time.tzinfo is None:
        at_time = at_time.replace(tzinfo=SHANGHAI_TZ)
    records = await get_autoban_records(fid)
    records.append({"time": at_time.isoformat(), "count": int(count)})
    await disk_cache.set(f"autoban:fid:{fid}", records, expire="10d")


async def get_autoban_count(fid: int, since: datetime) -> int:
    records = await get_autoban_records(fid)
    if not records:
        return 0

    total = 0
    for record in records:
        raw_time = record.get("time")
        count = record.get("count", 0)
        try:
            record_time = datetime.fromisoformat(raw_time) if isinstance(raw_time, str) else None
        except Exception:
            record_time = None
        if record_time and record_time.tzinfo is None:
            record_time = record_time.replace(tzinfo=SHANGHAI_TZ)
        if record_time and record_time >= since:
            total += int(count)
    return total


async def trim_autoban_records(fid: int, before: datetime) -> None:
    records = await get_autoban_records(fid)
    if not records:
        return

    keep: list[dict[str, Any]] = []
    for record in records:
        raw_time = record.get("time")
        try:
            record_time = datetime.fromisoformat(raw_time) if isinstance(raw_time, str) else None
        except Exception:
            record_time = None
        if record_time and record_time.tzinfo is None:
            record_time = record_time.replace(tzinfo=SHANGHAI_TZ)
        if record_time and record_time >= before:
            keep.append(record)

    await disk_cache.set(f"autoban:fid:{fid}", keep, expire="10d")
