import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from nonebot import get_app, get_bot, get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.adapters.onebot.v11.event import Sender
from nonebot.message import handle_event
from pydantic import BaseModel

from src.db import ApiUser

config = get_driver().config
SECRET_KEY = getattr(config, "secret_key", "default_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

message_id_pool = range(2**31, 2**32)


def message_id_gen():
    yield from message_id_pool


class Token(BaseModel):
    access_token: str
    token_type: str
    expire_in: int = 86400


class TokenData(BaseModel):
    username: str | None = None


class User(BaseModel):
    username: str


class UserInDB(User):
    hashed_password: str


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app: FastAPI = get_app()


def verify_password(plain_password, hashed_password):
    password_byte_enc = plain_password.encode("utf-8")
    hashed_password = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password=password_byte_enc, hashed_password=hashed_password)


def get_password_hash(password):
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
    return hashed_password


async def get_user(username: str):
    user = await ApiUser.find_one(ApiUser.username == username)
    if user:
        return UserInDB(username=user.username, hashed_password=user.hashed_password)


async def authenticate_user(username: str, password: str):
    user = await get_user(username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        token_data = TokenData(username=username)
        assert token_data.username is not None
    except InvalidTokenError:
        raise credentials_exception from None
    user = await get_user(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


@app.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    return Token(access_token=access_token, token_type="bearer")


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
async def checkout(body: Checkout, current_user: Annotated[User, Depends(get_current_user)]):
    driver = get_driver()
    bot = get_bot()
    event = GroupMessageEvent(
        time=int(time.time()),
        self_id=int(bot.self_id),
        post_type="message",
        sub_type="group",
        user_id=body.user_id,
        message_type="group",
        message_id=next(message_id_gen()),
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
async def delete(body: Delete, current_user: Annotated[User, Depends(get_current_user)]):
    driver = get_driver()
    bot = get_bot()
    event = GroupMessageEvent(
        time=int(time.time()),
        self_id=int(bot.self_id),
        post_type="message",
        sub_type="group",
        user_id=body.user_id,
        message_type="group",
        message_id=next(message_id_gen()),
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
async def ban(body: Ban, current_user: Annotated[User, Depends(get_current_user)]):
    driver = get_driver()
    bot = get_bot()
    event = GroupMessageEvent(
        time=int(time.time()),
        self_id=int(bot.self_id),
        post_type="message",
        sub_type="group",
        user_id=body.user_id,
        message_type="group",
        message_id=next(message_id_gen()),
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
