from pathlib import Path

from cashews import Cache

from src.common import Client

CACHE_DIR = Path.cwd() / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

tiebaname_cache = Cache()
tiebaname_cache.setup(f"disk://?directory={(CACHE_DIR / 'tieba_name_cache').as_posix()}&shards=0")


async def get_tieba_name(fid: int) -> str:
    key = f"fid:{fid}"
    if name := await tiebaname_cache.get(key):
        return name

    err_key = f"err:{fid}"
    if await tiebaname_cache.exists(err_key):
        return ""

    async with Client() as client:
        name = await client.get_fname(fid)

    if name:
        await tiebaname_cache.set(key, name)
    else:
        await tiebaname_cache.set(err_key, 1, expire=5)

    return name
