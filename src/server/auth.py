"""Password authentication with server sessions; no client-selected identities."""
import re
import secrets
import time
import unicodedata
from collections import OrderedDict
from sqlite3 import IntegrityError
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.server.session import (
    app_db, session_user, identity_info, issue_session, hash_token, COOKIE_NAME,
)

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(24))
attempts = OrderedDict()
attempt_lock = Lock()
WINDOW = 300
MAX_ATTEMPTS = 8


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        value = unicodedata.normalize("NFKC", value).casefold()
        if not re.fullmatch(r"[a-z0-9_]{3,32}", value):
            raise ValueError("用户名需为 3–32 位英文字母、数字或下划线")
        return value


class Registration(Credentials):
    keep_guest_data: bool = False


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def throttle(request):
    # Ignore untrusted proxy headers; limit by transport peer, including failed registrations.
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with attempt_lock:
        expired = [k for k, values in attempts.items() if now - values[-1] >= WINDOW]
        for entry in expired:
            attempts.pop(entry, None)
        values = [v for v in attempts.get(key, []) if now - v < WINDOW]
        if len(values) >= MAX_ATTEMPTS:
            raise HTTPException(429, "尝试过于频繁，请五分钟后重试", headers={"Retry-After": "300"})
        attempts[key] = [*values, now]
        attempts.move_to_end(key)
        if len(attempts) > 4096:
            attempts.popitem(last=False)


def register(data, request, response):
    throttle(request)
    identity = session_user(request)
    if identity_info(identity)["kind"] == "account":
        raise HTTPException(409, "请先退出当前账号")
    encoded = hasher.hash(data.password)
    try:
        with app_db() as db:
            db.execute("BEGIN IMMEDIATE")
            if data.keep_guest_data:
                # Revalidate under the write lock. A concurrent upgrade cannot adopt it twice.
                token = request.cookies.get(COOKIE_NAME, "")
                row = db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
                                 (hash_token(token), int(time.time()))).fetchone()
                if not row or db.execute("SELECT 1 FROM accounts WHERE user_id=?", (row[0],)).fetchone():
                    raise HTTPException(409, "访客会话已变化，请刷新后重试")
                identity = row[0]
                db.execute("DELETE FROM sessions WHERE user_id=?", (identity,))
            else:
                identity = secrets.token_hex(16)
            db.execute("INSERT INTO accounts(user_id,username,password_hash,created_at) VALUES (?,?,?,?)",
                       (identity, data.username, encoded, int(time.time())))
            issue_session(db, identity, request, response)
    except IntegrityError as error:
        raise HTTPException(409, "用户名不可用，请换一个") from error
    return identity_info(identity)


def login(data, request, response):
    throttle(request)
    with app_db() as db:
        row = db.execute("SELECT user_id,password_hash FROM accounts WHERE username=?",
                         (data.username,)).fetchone()
    try:
        hasher.verify(row[1] if row else dummy_hash, data.password)
    except (VerificationError, InvalidHashError):
        raise HTTPException(401, "用户名或密码错误")
    if not row:
        raise HTTPException(401, "用户名或密码错误")
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT password_hash FROM accounts WHERE user_id=?", (row[0],)).fetchone()
        if not current or current[0] != row[1]:
            raise HTTPException(401, "用户名或密码错误")
        if hasher.check_needs_rehash(row[1]):
            db.execute("UPDATE accounts SET password_hash=? WHERE user_id=?",
                       (hasher.hash(data.password), row[0]))
        issue_session(db, row[0], request, response)
    return identity_info(row[0])


def logout(request: Request, response: Response):
    with app_db() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?",
                   (hash_token(request.cookies.get(COOKIE_NAME, "")),))
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_NAME.startswith("__Host-"),
                           httponly=True, samesite="lax")
    return {"kind": "anonymous", "username": None}
