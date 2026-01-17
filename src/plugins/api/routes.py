import base64
from itertools import count
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from nonebot import get_app, get_bot, get_plugin_config
from pydantic import BaseModel

from src.common.cache import ClientCache, tieba_uid2user_info_cached
from src.common.service.basic import ban_user, delete_thread, generate_checkout_msg
from src.db.crud import get_group

from .config import Config

plugin_config = get_plugin_config(Config)

bearer_scheme = HTTPBearer(auto_error=False)

message_id_generator = count(2**31, 1)

app: FastAPI = get_app()


async def require_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]):
    if plugin_config.api_token is None:
        return None
    if credentials is None or credentials.credentials != plugin_config.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


class BaseBody(BaseModel):
    user_id: int
    group_id: int


class Checkout(BaseBody):
    tieba_uid: int


class Delete(BaseBody):
    thread_id: int


class Ban(BaseBody):
    tieba_uid: int
    days: int


@app.post("/api/checkout", status_code=status.HTTP_200_OK)
async def checkout(body: Checkout, _: Annotated[str | None, Depends(require_token)]):
    bot = get_bot()
    client = await ClientCache.get_bawu_client(body.group_id)
    user_info_t = await tieba_uid2user_info_cached(client, body.tieba_uid)
    base_content, image_bytes = await generate_checkout_msg(client, user_info_t.user_id)
    img_b64 = base64.b64encode(image_bytes).decode()
    message = [
        {"type": "text", "data": {"text": base_content}},
        {"type": "image", "data": {"file": f"base64://{img_b64}"}},
    ]
    await bot.call_api("send_group_msg", group_id=body.group_id, message=message)
    return {"status": "ok"}


@app.post("/api/delete", status_code=status.HTTP_200_OK)
async def delete(body: Delete, _: Annotated[str | None, Depends(require_token)]):
    bot = get_bot()
    group_info = await get_group(body.group_id)
    client = await ClientCache.get_bawu_client(body.group_id)
    result = await delete_thread(client, group_info, body.thread_id, uploader_id=body.user_id)
    await bot.call_api(
        "send_group_msg",
        group_id=body.group_id,
        message=[{"type": "text", "data": {"text": f"{'删除成功' if result else '删除失败'}。"}}],
    )
    return {"status": "ok"}


@app.post("/api/ban", status_code=status.HTTP_200_OK)
async def ban(body: Ban, _: Annotated[str | None, Depends(require_token)]):
    bot = get_bot()
    group_info = await get_group(body.group_id)
    client = await ClientCache.get_bawu_client(body.group_id)
    user_info_t = await tieba_uid2user_info_cached(client, body.tieba_uid)
    result = await ban_user(client, group_info, body.tieba_uid, days=body.days, uploader_id=user_info_t.user_id)
    await bot.call_api(
        "send_group_msg",
        group_id=body.group_id,
        message=[{"type": "text", "data": {"text": f"{'封禁成功' if result else '封禁失败'}。"}}],
    )
    return {"status": "ok"}
