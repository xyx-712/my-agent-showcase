"""Server-owned chat sessions, distinct from authentication sessions."""
from contextlib import contextmanager
from contextvars import ContextVar
import sqlite3
from uuid import uuid4
from fastapi import HTTPException


def app_db():
    from src.server.session import app_db as database
    return database()

current=ContextVar('chat_conversation',default=None)


def storage_session(user):
    scope=current.get()
    return scope['storage_session'] if scope and scope['user_id']==user else ''


def thread(user):
    scope=current.get()
    return scope['thread_id'] if scope and scope['user_id']==user else user


def scoped(user):
    scope=current.get()
    return scope is not None and scope['user_id']==user


def default(db,user):
    db.execute('INSERT OR IGNORE INTO conversations(id,user_id,name,is_default,thread_id,storage_session) VALUES (?,?,?,1,?,?)',
               (uuid4().hex,user,'默认会话',user,''))
    db.row_factory=sqlite3.Row
    return dict(db.execute('SELECT * FROM conversations WHERE user_id=? AND is_default=1',(user,)).fetchone())


def resolve(user,identity=None,allow_deleted=False):
    with app_db() as db:
        if identity is None:return default(db,user)
        db.row_factory=sqlite3.Row
        value=db.execute('SELECT * FROM conversations WHERE user_id=? AND id=?',(user,identity)).fetchone()
    if not value or value['deleted'] and not allow_deleted:raise HTTPException(404,'聊天会话不存在或已删除')
    return dict(value)


@contextmanager
def bind(user,identity=None):
    token=current.set(resolve(user,identity))
    try:yield
    finally:current.reset(token)


def listing(user):
    with app_db() as db:
        default(db,user)
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute('SELECT id,name,is_default,deleted,created_at FROM conversations WHERE user_id=? ORDER BY is_default DESC,created_at,id',(user,))]


def create(user,name):
    identity=uuid4().hex
    with app_db() as db:
        db.execute('BEGIN IMMEDIATE')
        default(db,user)
        if db.execute('SELECT count(*) FROM conversations WHERE user_id=?',(user,)).fetchone()[0]>=100:
            raise HTTPException(409,'聊天会话达到100个上限（含已删除会话）')
        db.execute('INSERT INTO conversations(id,user_id,name,thread_id,storage_session) VALUES (?,?,?,?,?)',
                   (identity,user,name,'chat:'+identity,identity))
    return resolve(user,identity)


def mark(user,identity,deleted):
    with app_db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.row_factory=sqlite3.Row
        value=db.execute('SELECT * FROM conversations WHERE user_id=? AND id=?',(user,identity)).fetchone()
        if not value:raise HTTPException(404,'聊天会话不存在')
        if value['is_default'] and deleted:raise HTTPException(409,'旧默认会话保留为兼容入口，请新建聊天会话后使用删除功能')
        db.execute('UPDATE conversations SET deleted=? WHERE user_id=? AND id=?',(int(deleted),user,identity))
    return {'id':identity,'deleted':deleted}
