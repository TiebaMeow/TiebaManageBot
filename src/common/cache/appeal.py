from .disk_cache import disk_cache


async def get_appeals(group_id: int) -> list[tuple[int, int]]:
    key = f"appeal:group:{group_id}"
    appeals = await disk_cache.get(key)
    if appeals is None:
        appeals = []
        await disk_cache.set(key, appeals, expire="2d")
    return appeals


async def set_appeals(group_id: int, appeals: list[tuple[int, int]]) -> None:
    key = f"appeal:group:{group_id}"
    await disk_cache.set(key, appeals, expire="2d")


async def get_appeal_id(message_id: int) -> tuple[int, int]:
    key = f"appeal:msg:{message_id}"
    appeal_info = await disk_cache.get(key)
    if not appeal_info:
        return 0, 0
    return appeal_info


async def set_appeal_id(message_id: int, appeal_info: tuple[int, int]) -> None:
    key = f"appeal:msg:{message_id}"
    await disk_cache.set(key, appeal_info, expire="2d")
    rev_key = f"appeal:rev:{appeal_info[0]}"
    await disk_cache.set(rev_key, message_id, expire="2d")


async def del_appeal_id(appeal_id: int) -> None:
    rev_key = f"appeal:rev:{appeal_id}"
    message_id = await disk_cache.get(rev_key)
    if message_id:
        await disk_cache.delete(f"appeal:msg:{message_id}")
        await disk_cache.delete(rev_key)
