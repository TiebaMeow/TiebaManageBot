import ssl
from typing import Literal

import httpx

from .interface import DBInterface
from .models import Image, ImgDataModel


class ImageUtils:
    context: ssl.SSLContext | None = None

    @classmethod
    async def download_and_save_img(
        cls, url: str, uploader_id: int, fid: int, note: str = ""
    ) -> ImgDataModel | Literal[-1, -2]:
        if cls.context is None:
            cls.context = ssl.create_default_context()
            cls.context.set_ciphers("DEFAULT")
        async with httpx.AsyncClient(verify=cls.context) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
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
