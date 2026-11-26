"""Chat replay protection. Incomplete requests must be reconciled via task continuation."""
import hashlib
import json
import time
import sqlite3
from fastapi import HTTPException
from src.server.session import app_db
from src.server.conversations import thread,storage_session


def init_requests():
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS chat_requests(
            user_id TEXT,id TEXT,fingerprint TEXT,state TEXT,response TEXT,created INTEGER,
            PRIMARY KEY(user_id,id))""")
        db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (5)")
        from src.server.migrations import thread_columns
        thread_columns(db,'chat_requests')


def begin(user_id, identity, payload):
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT fingerprint,state,response FROM chat_requests WHERE thread_id=? AND id=?",
                         (thread(user_id), identity)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise HTTPException(409, "相同请求 ID 的内容不能改变")
            if row[1] in {'failed', 'timed_out'}:
                saved = json.loads(row[2])
                raise HTTPException(saved['status_code'], saved['detail'])
            if row[1] not in {"completed", "recoverable"}:
                raise HTTPException(409, "此请求可能已部分执行，请使用新的「继续任务」消息核对")
            return json.loads(row[2])
        db.execute("DELETE FROM chat_requests WHERE created<? AND state='completed'", (int(time.time()) - 604800,))
        if db.execute("SELECT count(*) FROM chat_requests WHERE user_id=?", (user_id,)).fetchone()[0] >= 1000:
            raise HTTPException(429, "请求记录达到上限，请先备份整理数据")
        db.execute("INSERT INTO chat_requests(thread_id,id,fingerprint,state,response,created,user_id,session_id) VALUES (?,?,?,'running',NULL,?,?,?)",
                   (thread(user_id), identity, fingerprint, int(time.time()),user_id,storage_session(user_id)))
    return None


def complete(user_id, identity, response):
    with app_db() as db:
        state = 'recoverable' if response.get('task', {}).get('status') in {'waiting', 'paused'} else 'completed'
        updated = db.execute("UPDATE chat_requests SET state=?,response=? WHERE thread_id=? AND id=? AND state='running'",
                   (state, json.dumps(response, ensure_ascii=False), thread(user_id), identity)).rowcount
        if updated != 1:
            raise sqlite3.IntegrityError('Request finalization conflict')


def fail(user_id, identity, error):
    """Only called after synchronous execution unwinds. Never clear replay records."""
    code = error.status_code if isinstance(error, HTTPException) else 500
    detail = (error.detail if isinstance(error, HTTPException) else
              '本轮执行失败，可能已有部分进度；请使用新的「继续任务」消息核对，勿重放原请求。')
    with app_db() as db:
        updated = db.execute("UPDATE chat_requests SET state=?,response=? WHERE thread_id=? AND id=? AND state='running'",
            ('timed_out' if code == 504 else 'failed', json.dumps({'status_code': code, 'detail': detail}, ensure_ascii=False),
             thread(user_id), identity)).rowcount
        if updated != 1:
            raise sqlite3.IntegrityError('Request finalization conflict')


def run(user_id, identity, payload, execute):
    from src.agent.execution import request_budget
    try:
        if identity:
            cached = begin(user_id, identity, payload)
            if cached is not None:
                return cached
    except sqlite3.Error as error:
        raise HTTPException(503, '请求记录不可用，未启动执行；请稍后核对原请求状态。') from error
    try:
        with request_budget():
            result = execute()
    except sqlite3.Error as error:
        # Storage outcome is unknown: leave running untouched and refuse replay.
        raise HTTPException(503, '数据库异常，执行结果待核对；原请求保持保护状态，请勿重复提交。') from error
    except Exception as error:
        try:
            if identity:
                fail(user_id, identity, error)
        except sqlite3.Error as storage_error:
            raise HTTPException(503, '无法保存失败状态；原请求保持保护状态，请勿重复提交。') from storage_error
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(500, '本轮执行失败，请使用新的「继续任务」消息核对已保存进度。') from error
    try:
        if identity:
            complete(user_id, identity, result)
    except sqlite3.Error as error:
        raise HTTPException(503, '执行已结束但结果登记失败，请核对历史与任务，勿重放原请求。') from error
    return result
