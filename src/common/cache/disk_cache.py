from pathlib import Path

from cashews import Cache

CACHE_DIR = Path(__file__).parents[3] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

disk_cache = Cache()
disk_cache.setup(f"disk://?directory={(CACHE_DIR / 'disk_cache').as_posix()}&shards=0")
