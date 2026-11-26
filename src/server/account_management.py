"""Account sessions, password changes and opt-in email proof flows."""
from email.message import EmailMessage
import os
import re
import secrets
import smtplib
import time
from sqlite3 import IntegrityError
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, field_validator
from src.server import auth
from src.server.session import app_db, hash_token, issue_session, COOKIE_NAME


def init_account_management():
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)")}
        if "email" not in columns:
            db.execute("ALTER TABLE accounts ADD COLUMN email TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS accounts_email ON accounts(email) WHERE email IS NOT NULL")
        columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
        for column in ("device", "session_id"):
            if column not in columns:
                db.execute(f"ALTER TABLE sessions ADD COLUMN {column} TEXT")
        for token, in db.execute("SELECT token_hash FROM sessions WHERE session_id IS NULL").fetchall():
            db.execute("UPDATE sessions SET session_id=?,device='旧会话' WHERE token_hash=?", (uuid4().hex, token))
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS sessions_id ON sessions(session_id)")
        db.execute("""CREATE TABLE IF NOT EXISTS account_tokens(
            token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,purpose TEXT NOT NULL,
            email TEXT,expires_at INTEGER NOT NULL)""")
        db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (4)")


class PasswordChange(auth.EmptyRequest):
    current_password: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class EmailRequest(auth.EmptyRequest):
    email: str = Field(min_length=3, max_length=254)
    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("邮箱格式不正确")
        return value


class EmailBinding(EmailRequest):
    current_password: str = Field(min_length=10, max_length=128)


class TokenRequest(auth.EmptyRequest):
    token: str = Field(min_length=43, max_length=43)


class ResetRequest(TokenRequest):
    new_password: str = Field(min_length=10, max_length=128)


def account(user_id):
    with app_db() as db:
        row = db.execute("SELECT password_hash,email FROM accounts WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(403, "此操作需要注册账号")
    return row


def check_password(encoded, value):
    try:
        auth.hasher.verify(encoded, value)
    except (auth.VerificationError, auth.InvalidHashError):
        raise HTTPException(401, "密码验证失败")


def change_password(user_id, data, request, response):
    auth.throttle(request)
    encoded, _ = account(user_id)
    check_password(encoded, data.current_password)
    replacement = auth.hasher.hash(data.new_password)
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        result = db.execute("UPDATE accounts SET password_hash=? WHERE user_id=? AND password_hash=?",
                            (replacement, user_id, encoded))
        if not result.rowcount:
            raise HTTPException(409, "密码已变化，请重新登录")
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM account_tokens WHERE user_id=?", (user_id,))
        issue_session(db, user_id, request, response)
    return {"changed": True, "other_sessions_revoked": True}


def sessions(user_id, request):
    account(user_id)
    current = hash_token(request.cookies.get(COOKIE_NAME, ""))
    with app_db() as db:
        rows = db.execute("SELECT session_id,device,created_at,expires_at,token_hash FROM sessions WHERE user_id=? AND expires_at>?",
                          (user_id, int(time.time()))).fetchall()
    return [{"id": sid, "device": device, "created_at": created, "expires_at": expires,
             "current": token == current} for sid, device, created, expires, token in rows]


def revoke(user_id, identity=None):
    account(user_id)
    with app_db() as db:
        if identity:
            count = db.execute("DELETE FROM sessions WHERE user_id=? AND session_id=?", (user_id, identity)).rowcount
            if not count:
                raise HTTPException(404, "会话不存在")
        else:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"revoked": True}


def deliver(email, subject, token):
    host = os.environ.get("MY_AGENT_SMTP_HOST")
    sender = os.environ.get("MY_AGENT_SMTP_FROM")
    if not host or not sender:
        raise ValueError("邮件服务未配置")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, email, subject
    message.set_content("请在应用的账号管理页面输入一次性验证令牌，有效期 15 分钟。\n" + token)
    with smtplib.SMTP(host, int(os.environ.get("MY_AGENT_SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.starttls()
        if os.environ.get("MY_AGENT_SMTP_USER"):
            smtp.login(os.environ["MY_AGENT_SMTP_USER"], os.environ.get("MY_AGENT_SMTP_PASSWORD", ""))
        smtp.send_message(message)


def send_proof(user_id, purpose, email):
    token = secrets.token_urlsafe(32)
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        if purpose == "reset" and not db.execute("SELECT 1 FROM accounts WHERE user_id=? AND email=?", (user_id, email)).fetchone():
            return False
        db.execute("DELETE FROM account_tokens WHERE user_id=? AND purpose=?", (user_id, purpose))
        db.execute("INSERT INTO account_tokens VALUES (?,?,?,?,?)",
                   (hash_token(token), user_id, purpose, email, int(time.time()) + 900))
    try:
        deliver(email, "My Agent 邮箱验证" if purpose == "verify" else "My Agent 密码找回", token)
    except Exception:
        with app_db() as db:
            db.execute("DELETE FROM account_tokens WHERE token_hash=?", (hash_token(token),))
        return False
    return True


def request_email(user_id, data, request):
    auth.throttle(request)
    encoded, _ = account(user_id)
    check_password(encoded, data.current_password)
    if not send_proof(user_id, "verify", data.email):
        raise HTTPException(503, "邮件服务未配置或发送失败；本机可继续使用其他账号功能")
    return {"sent": True}


def verify_email(user_id, token):
    account(user_id)
    try:
        with app_db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT email FROM account_tokens WHERE token_hash=? AND user_id=? AND purpose='verify' AND expires_at>?",
                             (hash_token(token), user_id, int(time.time()))).fetchone()
            if not row:
                raise HTTPException(400, "验证令牌无效或已过期")
            db.execute("UPDATE accounts SET email=? WHERE user_id=?", (row[0], user_id))
            db.execute("DELETE FROM account_tokens WHERE user_id=?", (user_id,))
    except IntegrityError:
        raise HTTPException(409, "此邮箱无法绑定")
    return {"verified": True}


def background_proof(user_id, purpose, email):
    from src.server.coordination import operation
    try:
        with operation("mail:" + user_id):
            return send_proof(user_id, purpose, email)
    except HTTPException:
        return False


def forgot(data, request, background=None):
    auth.throttle(request)
    with app_db() as db:
        row = db.execute("SELECT user_id FROM accounts WHERE email=?", (data.email,)).fetchone()
    if row:
        if background is not None:
            background.add_task(background_proof, row[0], "reset", data.email)
        else:
            background_proof(row[0], "reset", data.email)
    return {"accepted": True, "message": "若邮箱已验证且邮件服务可用，将收到重置令牌"}


def reset(data, request):
    auth.throttle(request)
    encoded = auth.hasher.hash(data.new_password)
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT user_id FROM account_tokens WHERE token_hash=? AND purpose='reset' AND expires_at>?",
                         (hash_token(data.token), int(time.time()))).fetchone()
        if not row:
            raise HTTPException(400, "重置令牌无效或已过期")
        db.execute("UPDATE accounts SET password_hash=? WHERE user_id=?", (encoded, row[0]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (row[0],))
        db.execute("DELETE FROM account_tokens WHERE user_id=?", (row[0],))
    return {"reset": True}
