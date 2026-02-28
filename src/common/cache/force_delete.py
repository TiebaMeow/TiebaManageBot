from __future__ import annotations

from typing import TypedDict

from .disk_cache import disk_cache


class TaskInfo(TypedDict):
    bot_id: str
    thread_id: int
    message_id: int
    group_id: int
    fid: int
    operator_id: int
    expire_time: float  # timestamp
    attempts: int  # 尝试次数


KEY = "fd:tasks"


async def get_all_force_delete_records() -> dict[str, TaskInfo]:
    """获取所有持久化的任务记录"""
    tasks = await disk_cache.get(KEY)
    if tasks is None:
        tasks = {}
        await disk_cache.set(KEY, tasks, expire="30d")
    return tasks


async def add_force_delete_record(task_id: str, info: TaskInfo) -> None:
    """添加任务记录到持久化缓存"""
    tasks = await get_all_force_delete_records()
    tasks[task_id] = info
    await disk_cache.set(KEY, tasks, expire="30d")


async def remove_force_delete_record(task_id: str) -> None:
    """从持久化缓存移除任务记录"""
    tasks = await get_all_force_delete_records()
    if task_id in tasks:
        del tasks[task_id]
        await disk_cache.set(KEY, tasks, expire="30d")


async def save_force_delete_records(tasks: dict[str, TaskInfo]) -> None:
    """保存所有任务记录到持久化缓存"""
    await disk_cache.set(KEY, tasks, expire="30d")
