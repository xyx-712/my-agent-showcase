"""Cross-process operation leases and a shared maintenance barrier."""
from contextlib import contextmanager
from contextvars import ContextVar
import sqlite3
from threading import Event, Thread
import time
from uuid import uuid4
from fastapi import HTTPException
from src.server import session

LEASE_SECONDS = 90
current_lease = ContextVar("operation_lease", default=None)


def connection():
    path = session.APP_DB.with_name(session.APP_DB.stem + "_coordination.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS leases(owner TEXT PRIMARY KEY, scope TEXT, exclusive INTEGER, expires REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS workers(owner TEXT PRIMARY KEY,expires REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS maintenance(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT,expires REAL)")
    return db


def acquire(scope, exclusive):
    owner = uuid4().hex
    db = connection()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            db.execute("DELETE FROM leases WHERE expires<?", (now,))
            if db.execute("SELECT 1 FROM maintenance WHERE expires>?", (now,)).fetchone():
                raise HTTPException(503, "正在备份或恢复，请稍后重试")
            if exclusive and db.execute("SELECT 1 FROM leases WHERE scope=? AND exclusive=1", (scope,)).fetchone():
                raise HTTPException(409, "此身份已有操作执行中，请等待完成后重试")
            db.execute("INSERT INTO leases VALUES (?,?,?,?)", (owner, scope, int(exclusive), now + LEASE_SECONDS))
    finally:
        db.close()
    return owner


def check_lease():
    owner = current_lease.get()
    if owner is None:
        return
    db = connection()
    try:
        if not db.execute("SELECT 1 FROM leases WHERE owner=? AND expires>?", (owner, time.time())).fetchone():
            raise HTTPException(409, "执行租约已失效，请继续任务核对持久化结果")
    finally:
        db.close()


@contextmanager
def operation(scope, exclusive=True):
    owner = acquire(scope, exclusive)
    token = current_lease.set(owner)
    stop = Event()
    def renew():
        while not stop.wait(10):
            db = connection()
            try:
                with db:
                    db.execute("UPDATE leases SET expires=? WHERE owner=? AND expires>?",
                               (time.time() + LEASE_SECONDS, owner, time.time()))
            finally:
                db.close()
    thread = Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
        check_lease()
    finally:
        stop.set()
        thread.join(timeout=2)
        current_lease.reset(token)
        db = connection()
        try:
            with db:
                db.execute("DELETE FROM leases WHERE owner=?", (owner,))
        finally:
            db.close()


@contextmanager
def maintenance():
    owner = uuid4().hex
    db = connection()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            db.execute("DELETE FROM leases WHERE expires<?", (now,))
            if db.execute("SELECT 1 FROM leases").fetchone() or db.execute("SELECT 1 FROM maintenance WHERE expires>?", (now,)).fetchone():
                raise RuntimeError("仍有运行中的请求或维护任务，请等待其结束后重试")
            db.execute("INSERT OR REPLACE INTO maintenance VALUES (1,?,?)", (owner, now + LEASE_SECONDS))
        stop = Event()
        def renew_maintenance():
            while not stop.wait(10):
                renewal = connection()
                try:
                    with renewal:
                        renewal.execute("UPDATE maintenance SET expires=? WHERE owner=? AND expires>?",
                                        (time.time() + LEASE_SECONDS, owner, time.time()))
                finally:
                    renewal.close()
        thread = Thread(target=renew_maintenance, daemon=True)
        thread.start()
        try:
            yield owner
        finally:
            stop.set()
            thread.join(timeout=2)
    finally:
        with db:
            db.execute("DELETE FROM maintenance WHERE owner=?", (owner,))
        db.close()


@contextmanager
def worker_lifetime():
    owner = uuid4().hex
    stop = Event()
    def update():
        db = connection()
        try:
            with db:
                db.execute("INSERT OR REPLACE INTO workers VALUES (?,?)", (owner, time.time() + LEASE_SECONDS))
        finally:
            db.close()
    update()
    def renew():
        while not stop.wait(10):
            update()
    thread = Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)
        db = connection()
        try:
            with db:
                db.execute("DELETE FROM workers WHERE owner=?", (owner,))
        finally:
            db.close()


def require_offline():
    db = connection()
    try:
        if db.execute("SELECT 1 FROM workers WHERE expires>?", (time.time(),)).fetchone():
            raise RuntimeError("恢复需要停止全部 worker；异常退出后等待租约过期再重试")
    finally:
        db.close()


def maintenance_action(owner, action):
    db = connection()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM maintenance WHERE owner=? AND expires>?", (owner, time.time())).fetchone():
                raise RuntimeError("维护租约已失效，停止写入；请核对恢复标记后重试")
            return action()
    finally:
        db.close()
