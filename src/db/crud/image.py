from typing import Literal

from tiebameow.client import HTTPXClient

from src.db.models import Image, ImgDataModel
from src.db.session import get_session


async def download_and_save_img(url: str, uploader_id: int, fid: int, note: str = "") -> ImgDataModel | Literal[-1, -2]:
    try:
        resp = await HTTPXClient.get(url, follow_redirects=True)
        if resp is None:
            return -1

        if len(resp.content) > 10 * 1024 * 1024:
            return -2

        return await save_image(uploader_id, fid, resp.content, note)
    except Exception:
        return -1


async def save_image(uploader_id: int, fid: int, img: bytes, note: str = "") -> ImgDataModel:
    image_data = Image(img=img)
    async with get_session() as session:
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


async def get_image_data(img_id: int) -> bytes | None:
    try:
        async with get_session() as session:
            image = await session.get(Image, img_id)
            if image:
                return image.img
    except Exception:
        return None
    return None


async def delete_image(img_id: int) -> bool:
    try:
        async with get_session() as session:
            image_doc = await session.get(Image, img_id)
            if image_doc:
                await session.delete(image_doc)
                await session.commit()
            return True
    except Exception:
        pass
    return False
