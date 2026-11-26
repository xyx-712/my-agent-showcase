import hashlib
import os
import secrets
import time
from contextlib import contextmanager
from sqlite3 import connect

from fastapi import HTTPException, Request, Response
from src.config import APP_DB, IS_DEMO
from src.server.migrations import migrate_sessions

COOKIE_NAME = "__Host-my_agent_session" if IS_DEMO else "my_agent_local_session"
SESSION_SECONDS = int(os.environ.get("MY_AGENT_SESSION_SECONDS", str(7 * 24 * 60 * 60)))
if not 60 <= SESSION_SECONDS <= 30 * 24 * 60 * 60:
    raise RuntimeError("MY_AGENT_SESSION_SECONDS must be between 60 and 2592000")


@contextmanager
def app_db():
    APP_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(APP_DB, timeout=30)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_sessions():
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        migrate_sessions(db)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) != 43 or not token.isascii():
        return None
    with app_db() as db:
        row = db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
                         (hash_token(token), int(time.time()))).fetchone()
    return row[0] if row else None


def require_user(request: Request):
    identity = session_user(request)
    if identity is None:
        raise HTTPException(401, "登录或访客会话已过期，请重新登录或进入访客模式")
    return identity


def issue_session(db, identity, request, response):
    old = request.cookies.get(COOKIE_NAME)
    if old:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(old),))
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
    if "session_id" in columns:
        from uuid import uuid4
        db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,session_id,device) VALUES (?,?,?,?,?,?)",
                   (hash_token(token), identity, now, now + SESSION_SECONDS, uuid4().hex,
                    request.headers.get("user-agent", "未知设备")[:160]))
    else:
        db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES (?,?,?,?)",
                   (hash_token(token), identity, now, now + SESSION_SECONDS))
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=IS_DEMO, samesite="lax", path="/")


def ensure_session(request: Request, response: Response):
    if session_user(request) is not None:
        return
    with app_db() as db:
        issue_session(db, secrets.token_hex(16), request, response)


def identity_info(identity):
    if identity is None:
        return {"kind": "anonymous", "username": None}
    with app_db() as db:
        row = db.execute("SELECT username FROM accounts WHERE user_id=?", (identity,)).fetchone()
    return {"kind": "account" if row else "guest", "username": row[0] if row else None}
