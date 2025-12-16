import time
from itertools import count
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from nonebot import get_app, get_bot, get_driver, get_plugin_config
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.adapters.onebot.v11.event import Sender
from nonebot.message import handle_event
from pydantic import BaseModel

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
    driver = get_driver()
    bot = get_bot()
    event = GroupMessageEvent(
        time=int(time.time()),
        self_id=int(bot.self_id),
        post_type="message",
        sub_type="group",
        user_id=body.user_id,
        message_type="group",
        message_id=next(message_id_generator),
        message=Message([MessageSegment.text(f"/查成分 {body.tieba_uid}")]),
        original_message=Message([MessageSegment.text(f"/查成分 {body.tieba_uid}")]),
        raw_message=f"/查成分 {body.tieba_uid}",
        font=0,
        sender=Sender(
            user_id=body.user_id,
        ),
        group_id=body.group_id,
    )
    driver.task_group.start_soon(handle_event, bot, event)
    return {"status": "ok"}


@app.post("/api/delete", status_code=status.HTTP_200_OK)
async def delete(body: Delete, _: Annotated[str | None, Depends(require_token)]):
    driver = get_driver()
    bot = get_bot()
    event = GroupMessageEvent(
        time=int(time.time()),
        self_id=int(bot.self_id),
        post_type="message",
        sub_type="group",
        user_id=body.user_id,
        message_type="group",
        message_id=next(message_id_generator),
        message=Message([MessageSegment.text(f"/删贴 {body.thread_id}")]),
        original_message=Message([MessageSegment.text(f"/删贴 {body.thread_id}")]),
        raw_message=f"/删贴 {body.thread_id}",
        font=0,
        sender=Sender(
            user_id=body.user_id,
        ),
        group_id=body.group_id,
    )
    driver.task_group.start_soon(handle_event, bot, event)
    return {"status": "ok"}


@app.post("/api/ban", status_code=status.HTTP_200_OK)
async def ban(body: Ban, _: Annotated[str | None, Depends(require_token)]):
    driver = get_driver()
    bot = get_bot()
    event = GroupMessageEvent(
        time=int(time.time()),
        self_id=int(bot.self_id),
        post_type="message",
        sub_type="group",
        user_id=body.user_id,
        message_type="group",
        message_id=next(message_id_generator),
        message=Message([MessageSegment.text(f"/封禁 {body.days} {body.tieba_uid}")]),
        original_message=Message([MessageSegment.text(f"/封禁 {body.days} {body.tieba_uid}")]),
        raw_message=f"/封禁 {body.days} {body.tieba_uid}",
        font=0,
        sender=Sender(
            user_id=body.user_id,
        ),
        group_id=body.group_id,
    )
    driver.task_group.start_soon(handle_event, bot, event)
    return {"status": "ok"}
