"""Authentication and legacy migration acceptance, with temporary databases only."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import time

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
PASSWORD = "  demo password 123  "


def run():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, directory / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = directory / "legacy.json"
        history.HISTORY_FILE.write_text(json.dumps({"old-guest": [{"role": "user", "content": "old message"}]}))
        with sqlite3.connect(config.APP_DB) as db:
            db.execute("CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL UNIQUE,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)")
        db.close()
        from src.server.api import app, general_agent
        from src.server import auth
        from src.server.session import COOKIE_NAME, app_db, hash_token, init_sessions
        from src.server.history import get_history, init_history, save_history
        from src.server.schedule_tasks import save_task, load_task
        from src.memory.store import memory_store
        class Model:
            def invoke(self, messages):
                if "规划普通聊天任务" in messages[0].content:
                    return AIMessage(content='{"action":"chat","steps":[],"question":""}')
                return AIMessage(content="离线聊天已完成")
        general_agent.llm = Model()
        with TestClient(app, headers=ORIGIN) as a, TestClient(app, headers=ORIGIN) as b:
            assert len(get_history("old-guest")) == 1
            init_sessions(); init_history()
            assert len(get_history("old-guest")) == 1
            assert a.get("/auth/me").json()["kind"] == "anonymous"
            assert a.get("/documents").status_code == 401
            assert a.post("/auth/login", headers={"Origin": "https://evil.test"}, json={}).status_code == 403
            a.post("/session", json={}).raise_for_status()
            guest_token = a.cookies[COOKIE_NAME]
            with app_db() as db:
                uid = db.execute("SELECT user_id FROM sessions WHERE token_hash=?", (hash_token(guest_token),)).fetchone()[0]
            save_history(uid, "user", "guest message")
            memory_store.save(uid, "name", "Fictional User")
            save_task(uid, {"id": "pending-task", "status": "waiting", "pending": "calculator"})
            # Exercise actual checkpoint creation under the same immutable identity.
            a.post("/chat", json={"message": "你好", "mode": "chat"}).raise_for_status()
            upload = a.post("/documents", files={"file": ("fiction.txt", b"fictional document")}).json()["id"]
            assert a.post("/auth/register", json={"username": "Demo_User", "password": PASSWORD, "keep_guest_data": True}).status_code == 200
            assert a.get("/auth/me").json() == {"kind": "account", "username": "demo_user"}
            assert a.cookies[COOKIE_NAME] != guest_token
            assert load_task(uid)["id"] == "pending-task"
            assert memory_store.get(uid, "name") == "Fictional User"
            assert general_agent.graph.get_state({"configurable": {"thread_id": uid}}).values
            with app_db() as db:
                assert db.execute("SELECT user_id FROM accounts").fetchone()[0] == uid
                stored = db.execute("SELECT password_hash FROM accounts").fetchone()[0]
                assert stored.startswith("$argon2id$") and PASSWORD not in stored
                assert not db.execute("SELECT 1 FROM sessions WHERE token_hash=?", (hash_token(guest_token),)).fetchone()
                assert not db.execute("SELECT 1 FROM sessions WHERE token_hash=?", (a.cookies[COOKIE_NAME],)).fetchone()
            # Another browser can access the same identity after login.
            b.post("/auth/login", json={"username": "DEMO_USER", "password": PASSWORD}).raise_for_status()
            assert b.get("/documents/"+upload).status_code == 200
            assert b.get("/history").json()["messages"] == a.get("/history").json()["messages"]
            assert b.get("/task").json()["id"] == "pending-task"
            login_token = b.cookies[COOKIE_NAME]
            b.post("/auth/login", json={"username": "demo_user", "password": PASSWORD}).raise_for_status()
            with app_db() as db:
                assert not db.execute("SELECT 1 FROM sessions WHERE token_hash=?", (hash_token(login_token),)).fetchone()
            a.post("/auth/logout", json={}).raise_for_status()
            a.cookies.set(COOKIE_NAME, guest_token)
            assert a.get("/history").status_code == 401
            a.cookies.clear()
            a.post("/session", json={}).raise_for_status()
            assert a.get("/history").json()["messages"] == []
            assert a.get("/documents/"+upload).status_code == 404
            a.post("/documents", files={"file": ("guest.txt", b"guest data")}).raise_for_status()
            auth.attempts.clear()
            a.post("/auth/register", json={"username": "second_user", "password": PASSWORD, "keep_guest_data": False}).raise_for_status()
            assert a.get("/documents").json()["files"] == []
            assert a.get("/task").json()["id"] is None
            assert a.get("/documents/"+upload).status_code == 404
            assert a.post("/chat", json={"message": "x", "user_id": uid}).status_code == 422
            assert a.get("/history", params={"user_id": uid}).status_code == 422
            assert a.get("/documents/not-a-file-id").status_code == 404
            assert a.post("/auth/login", json={"username": "demo_user", "password": PASSWORD.strip()}).status_code == 401
            assert a.post("/auth/login", json={"username": "missing_user", "password": PASSWORD}).json()["detail"] == "用户名或密码错误"
            assert a.post("/auth/register", json={"username": "DEMO_USER", "password": PASSWORD}).status_code == 409
            auth.attempts.clear()
            with ThreadPoolExecutor(max_workers=2) as pool:
                def register_once(_):
                    with TestClient(app, headers=ORIGIN) as client:
                        return client.post("/auth/register", json={"username": "race_user", "password": PASSWORD}).status_code
                assert sorted(pool.map(register_once, range(2))) == [200, 409]
            auth.attempts.clear()
            for _ in range(auth.MAX_ATTEMPTS):
                assert a.post("/auth/login", json={"username": "demo_user", "password": "wrong password"}).status_code == 401
            assert a.post("/auth/login", json={"username": "demo_user", "password": PASSWORD}).status_code == 429
            with app_db() as db:
                db.execute("UPDATE sessions SET expires_at=?", (int(time.time()) - 1,))
            assert b.get("/documents").status_code == 401
        general_agent.conn.close()

        # Invalid legacy input rolls back its import and can be retried after repair.
        with app_db() as db:
            db.execute("DELETE FROM schema_migrations WHERE version=2")
            db.execute("DELETE FROM chat_messages")
        history.HISTORY_FILE.write_text(json.dumps({"old": [{"role": "user", "content": "valid"}, {"role": "bad"}]}))
        try:
            init_history()
            raise AssertionError("bad legacy input accepted")
        except ValueError:
            assert get_history("old") == []
        history.HISTORY_FILE.write_text(json.dumps({"old": [{"role": "user", "content": "repaired"}]}))
        init_history(); init_history()
        assert len(get_history("old")) == 1
    print("PASS auth, migration rollback, identity upgrade, cross-browser isolation, token rotation, race and throttle")


if __name__ == "__main__":
    run()

