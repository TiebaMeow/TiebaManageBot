import base64
import ssl
from typing import Literal

import httpx
from bson import ObjectId

from .modules import ImageDocument, ImgData


class ImageUtils:
    """图片操作工具类"""

    context: ssl.SSLContext | None = None

    @classmethod
    async def download_and_save_img(
        cls, url: str, uploader_id: int, fid: int, note: str = ""
    ) -> ImgData | Literal[-1, -2]:
        """下载图片并保存"""
        if cls.context is None:
            cls.context = ssl.create_default_context()
            cls.context.set_ciphers("DEFAULT")
        async with httpx.AsyncClient(verify=cls.context) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return -1
            if len(resp.content) > 10 * 1024 * 1024:
                return -2
            img_base64 = base64.b64encode(resp.content).decode()
            return await cls.save_image(uploader_id, fid, img_base64, note)

    @staticmethod
    async def save_image(uploader_id: int, fid: int, img_base64: str, note: str = "") -> ImgData:
        """保存图片并返回ImgData"""
        # 只存储图片数据到ImageDocument
        image_doc = ImageDocument(img=img_base64)
        await image_doc.save()

        # 返回包含引用的ImgData
        return ImgData(
            uploader_id=uploader_id,
            fid=fid,
            image_id=str(image_doc.id),
            note=note,
        )

    @staticmethod
    async def get_image_data(img_data: ImgData) -> str | None:
        """根据ImgData获取base64图片数据"""
        try:
            image_doc = await ImageDocument.get(ObjectId(img_data.image_id))
            return image_doc.img if image_doc else None
        except Exception:
            return None

    @staticmethod
    async def delete_image(img_data: ImgData) -> bool:
        """删除图片"""
        try:
            image_doc = await ImageDocument.get(ObjectId(img_data.image_id))
            if image_doc:
                await image_doc.delete()
                return True
        except Exception:
            pass
        return False
