from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from cashews import Cache

CACHE_DIR = Path(__file__).parents[3] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

force_delete_cache = Cache()
force_delete_cache.setup(f"disk://?directory={(CACHE_DIR / 'force_delete_cache').as_posix()}&shards=0")


class TaskInfo(TypedDict):
    bot_id: str
    message_id: int
    group_id: int
    fid: int
    operator_id: int
    expire_time: float  # timestamp
    attempts: int  # 尝试次数


KEY = "force_delete_tasks"


async def get_all_force_delete_records() -> dict[int, TaskInfo]:
    """获取所有持久化的任务记录"""
    tasks = await force_delete_cache.get(KEY)
    if tasks is None:
        tasks = {}
        await force_delete_cache.set(KEY, tasks, expire="30d")
    return tasks


async def add_force_delete_record(tid: int, info: TaskInfo) -> None:
    """添加任务记录到持久化缓存"""
    tasks = await get_all_force_delete_records()
    tasks[tid] = info
    await force_delete_cache.set(KEY, tasks, expire="30d")


async def remove_force_delete_record(tid: int) -> None:
    """从持久化缓存移除任务记录"""
    tasks = await get_all_force_delete_records()
    if tid in tasks:
        del tasks[tid]
        await force_delete_cache.set(KEY, tasks, expire="30d")


async def save_force_delete_records(tasks: dict[int, TaskInfo]) -> None:
    """保存所有任务记录到持久化缓存"""
    await force_delete_cache.set(KEY, tasks, expire="30d")
