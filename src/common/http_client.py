import asyncio
import ssl
from contextlib import asynccontextmanager
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter


class HTTPXClient:
    _client: httpx.AsyncClient | None = None
    _context: ssl.SSLContext | None = None
    _lock: asyncio.Lock | None = None

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
    def _get_lock(cls) -> asyncio.Lock:
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    @asynccontextmanager
    async def get_client(cls):
        if cls._client is None or cls._client.is_closed:
            async with cls._get_lock():
                if cls._client is None or cls._client.is_closed:
                    if cls._context is None:
                        cls._context = ssl.create_default_context()
                        cls._context.set_ciphers("DEFAULT")
                    cls._client = httpx.AsyncClient(
                        timeout=cls.DEFAULT_TIMEOUT,
                        verify=cls._context,
                    )
        yield cls._client

    @classmethod
    async def close(cls):
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
