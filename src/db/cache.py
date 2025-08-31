import asyncio

from beanie import Document
from playwright.async_api import async_playwright

from src.common import Client

from .modules import GroupInfo

__all__ = ["GroupCache", "TiebaNameCache", "ChromiumCache"]


class GroupCache:
    """
    为群配置项提供缓存机制，无需实例化。
    """

    _cache: dict = {}
    _model_class: type[GroupInfo] = GroupInfo
    _primary_key: str = "group_id"
    _lock = asyncio.Lock()

    @classmethod
    async def load_data(cls):
        """
        从数据库加载所有数据到缓存（好像没这个必要）。
        """
        async with cls._lock:
            docs = await cls._model_class.find_all().to_list()
            cls._cache = {getattr(doc, cls._primary_key): doc for doc in docs}

    @classmethod
    async def get(cls, key_id: int) -> GroupInfo | None:
        """
        根据主键从缓存中获取对象。如果缓存中不存在，则从数据库加载。

        :param key_id: 主键值
        :return: 缓存中的文档或从数据库加载的文档
        """
        async with cls._lock:
            obj = cls._cache.get(key_id)
            if obj is None:
                obj = await cls._model_class.find_one({cls._primary_key: key_id})
                if obj:
                    cls._cache[getattr(obj, cls._primary_key)] = obj  # 更新缓存
        return obj

    @classmethod
    async def query(cls, **filters) -> list[GroupInfo]:
        """
        根据条件从缓存中查询对象。如果缓存中没有符合条件的对象，将从数据库查询。

        :param filters: 查询条件
        :return: 符合条件的文档列表
        """
        async with cls._lock:
            results = [doc for doc in cls._cache.values() if cls._matches(doc, filters)]
            if not results:
                results = await cls._model_class.find(filters).to_list()
                for doc in results:
                    cls._cache[getattr(doc, cls._primary_key)] = doc  # 更新缓存
        return results

    @classmethod
    async def add(cls, obj: GroupInfo) -> None:
        """
        添加一个对象到缓存中，并保存到数据库。

        :param obj: 新的文档对象
        """
        async with cls._lock:
            inserted = await obj.insert()  # 保存到数据库
            cls._cache[getattr(inserted, cls._primary_key)] = inserted  # 更新缓存

    @classmethod
    async def update(cls, key_id: int, **kwargs) -> None:
        """
        更新缓存和数据库中的对象。

        :param pk: 主键值
        :param kwargs: 要更新的字段及其值
        """
        async with cls._lock:
            if key_id not in cls._cache:
                raise KeyError(f"主键为 {key_id} 的对象不存在于缓存中。")
            obj = cls._cache[key_id]
            for key, value in kwargs.items():
                setattr(obj, key, value)
            await obj.save()  # 保存变更到数据库
            cls._cache[getattr(obj, cls._primary_key)] = obj  # 更新缓存

    @classmethod
    async def delete(cls, key_id: int) -> None:
        """
        从缓存和数据库中删除一个对象。

        :param pk: 主键值
        """
        async with cls._lock:
            if key_id not in cls._cache:
                raise KeyError(f"主键为 {key_id} 的对象不存在于缓存中。")
            obj = cls._cache.pop(key_id)  # 从缓存中移除
            await obj.delete()  # 从数据库中删除

    @classmethod
    async def all(cls) -> list[GroupInfo]:
        """
        返回缓存中的所有对象。

        :return: 缓存中的所有对象列表
        """
        async with cls._lock:
            return list(cls._cache.values())

    @classmethod
    async def reload(cls):
        """
        重新从数据库加载数据到缓存。
        """
        await cls.load_data()

    @staticmethod
    def _matches(obj: Document, filters) -> bool:
        """
        判断对象是否匹配查询条件。

        :param obj: 要检查的对象
        :param filters: 查询条件
        :return: 如果匹配条件返回 True，否则返回 False
        """
        for key, value in filters.items():
            if getattr(obj, key, None) != value:
                return False
        return True


class TiebaNameCache:
    _cache: dict = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get(cls, fid: int) -> str:
        async with cls._lock:
            name = cls._cache.get(fid)
            if name is None:
                name = await cls._fetch(fid)
                cls._cache[fid] = name
        return name

    @classmethod
    async def _fetch(cls, fid: int) -> str:
        async with Client() as client:
            return await client.get_fname(fid)


class AppealCache:
    _appeal_lists: dict[int, list[tuple[int, int]]] = {}
    _appeal_ids: dict[int, tuple[int, int]] = {}

    @classmethod
    async def get_appeals(cls, group_id: int) -> list[tuple[int, int]]:
        appeals = cls._appeal_lists.get(group_id)
        if appeals is None:
            appeals = []
            cls._appeal_lists[group_id] = appeals
        return appeals

    @classmethod
    async def set_appeals(cls, group_id: int, appeals: list[tuple[int, int]]):
        cls._appeal_lists[group_id] = appeals

    @classmethod
    async def get_appeal_id(cls, message_id: int) -> tuple[int, int]:
        appeal_info = cls._appeal_ids.get(message_id)
        if not appeal_info:
            return 0, 0
        return appeal_info

    @classmethod
    async def set_appeal_id(cls, message_id: int, appeal_info: tuple[int, int]):
        cls._appeal_ids[message_id] = appeal_info

    @classmethod
    async def del_appeal_id(cls, appeal_id: int):
        for message_id, appeal_info in list(cls._appeal_ids.items()):
            if appeal_info[0] == appeal_id:
                del cls._appeal_ids[message_id]
                break


class ChromiumCache:
    # 将浏览器实例放入类属性中
    _p = None
    browser = None
    context = None

    @classmethod
    async def initialize(cls):
        if cls._p is None:
            cls._p = await async_playwright().start()
            cls.browser = await cls._p.chromium.launch(
                headless=True,
                args=[
                    "--allow-file-access-from-files"  # 允许加载本地文件
                ],
            )
            cls.context = await cls.browser.new_context()

    @classmethod
    async def close(cls):
        # 清理资源
        if cls.context:
            try:
                await cls.context.close()
            except Exception:
                pass
            finally:
                cls.context = None
        if cls.browser:
            try:
                await cls.browser.close()
            except Exception:
                pass
            finally:
                cls.browser = None
        if cls._p:
            try:
                await cls._p.stop()
            except Exception:
                pass
            finally:
                cls._p = None
