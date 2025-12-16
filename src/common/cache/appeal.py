from pathlib import Path

from cashews import Cache

CACHE_DIR = Path.cwd() / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

appeal_cache = Cache()
appeal_cache.setup(f"disk://?directory={(CACHE_DIR / 'appeal_cache').as_posix()}&shards=0")


async def get_appeals(group_id: int) -> list[tuple[int, int]]:
    key = f"group:{group_id}"
    appeals = await appeal_cache.get(key)
    if appeals is None:
        appeals = []
        await appeal_cache.set(key, appeals, expire="2d")
    return appeals


async def set_appeals(group_id: int, appeals: list[tuple[int, int]]) -> None:
    key = f"group:{group_id}"
    await appeal_cache.set(key, appeals, expire="2d")


async def get_appeal_id(message_id: int) -> tuple[int, int]:
    key = f"msg:{message_id}"
    appeal_info = await appeal_cache.get(key)
    if not appeal_info:
        return 0, 0
    return appeal_info


async def set_appeal_id(message_id: int, appeal_info: tuple[int, int]) -> None:
    key = f"msg:{message_id}"
    await appeal_cache.set(key, appeal_info, expire="2d")
    rev_key = f"rev:{appeal_info[0]}"
    await appeal_cache.set(rev_key, message_id, expire="2d")


async def del_appeal_id(appeal_id: int) -> None:
    rev_key = f"rev:{appeal_id}"
    message_id = await appeal_cache.get(rev_key)
    if message_id:
        await appeal_cache.delete(f"msg:{message_id}")
        await appeal_cache.delete(rev_key)
