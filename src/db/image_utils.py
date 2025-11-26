import asyncio
import ssl
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .interface import DBInterface
from .models import Image, ImgDataModel


class HTTPXClient:
    _client: httpx.AsyncClient | None = None
    _context: ssl.SSLContext | None = None
    _lock = asyncio.Lock()

    DEFAULT_TIMEOUT = 10.0

    DEFAULT_RETRY = {
        "stop": stop_after_attempt(3),
        "wait": wait_exponential_jitter(initial=0.5, max=3.0),
        "retry": retry_if_exception_type((
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        )),
    }

    @classmethod
    @asynccontextmanager
    async def get_client(cls):
        async with cls._lock:
            if cls._context is None:
                cls._context = ssl.create_default_context()
                cls._context.set_ciphers("DEFAULT")
            if cls._client is None or cls._client.is_closed:
                cls._client = httpx.AsyncClient(
                    timeout=cls.DEFAULT_TIMEOUT,
                    verify=cls._context,
                )
            try:
                yield cls._client
            except httpx.TransportError:
                await cls.close()
                cls._client = None
                raise
            except httpx.HTTPError:
                raise

    @classmethod
    async def close(cls):
        async with cls._lock:
            if cls._client and not cls._client.is_closed:
                await cls._client.aclose()
                cls._client = None

    @classmethod
    def configure_defaults(cls, timeout: float = DEFAULT_TIMEOUT, retry_config: dict[str, Any] | None = None):
        cls.DEFAULT_TIMEOUT = timeout

        if retry_config:
            cls.DEFAULT_RETRY.update(retry_config)

    @classmethod
    async def get(cls, url: str, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _get():
            async with cls.get_client() as client:
                response = await client.get(url, **kwargs)
                response.raise_for_status()
                return response

        try:
            return await _get()
        except httpx.HTTPStatusError:
            return None

    @classmethod
    async def post(cls, url: str, json: dict[str, Any] | None = None, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _post():
            async with cls.get_client() as client:
                response = await client.post(url, json=json, **kwargs)
                response.raise_for_status()
                return response

        try:
            return await _post()
        except Exception:
            return None


class ImageUtils:
    @classmethod
    async def download_and_save_img(
        cls, url: str, uploader_id: int, fid: int, note: str = ""
    ) -> ImgDataModel | Literal[-1, -2]:
        resp = await HTTPXClient.get(url)
        if resp is None:
            return -1
        if len(resp.content) > 10 * 1024 * 1024:
            return -2
        img = resp.content
        return await cls.save_image(uploader_id, fid, img, note)

    @staticmethod
    async def save_image(uploader_id: int, fid: int, img: bytes, note: str = "") -> ImgDataModel:
        image_data = Image(img=img)
        async with DBInterface.get_session() as session:
            session.add(image_data)
            await session.commit()
            await session.refresh(image_data)
            img_id = image_data.id

        return ImgDataModel(
            uploader_id=uploader_id,
            fid=fid,
            image_id=img_id,
            note=note,
        )

    @staticmethod
    async def get_image_data(img_id: int) -> bytes | None:
        try:
            async with DBInterface.get_session() as session:
                image = await session.get(Image, img_id)
                if image:
                    return image.img
        except Exception:
            return None

    @staticmethod
    async def delete_image(img_id: int) -> bool:
        try:
            async with DBInterface.get_session() as session:
                image_doc = await session.get(Image, img_id)
                if image_doc:
                    await session.delete(image_doc)
                return True
        except Exception:
            pass
        return False
