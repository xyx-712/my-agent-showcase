"""Cross-process leases, chat replay protection, consistent backup and offline restore."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
from tests.attachment_evaluation import FakeModel, HEADERS, FIXTURES


def child(path):
    from src.server import session
    session.APP_DB = Path(path) / "APP_DB.db"
    from src.server.coordination import operation
    with operation("held-identity"):
        (Path(path) / "ready").write_text("ready")
        time.sleep(3)


def run():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, directory / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = directory / "history.json"
        from src.server.api import app, general_agent
        from src.server.backup import backup, restore
        from src.server.coordination import operation
        from src.server.session import app_db
        try:
            backup(directory / "incomplete-backup")
            raise AssertionError("incomplete backup published")
        except ValueError:
            assert not (directory / "incomplete-backup").exists()
        from langchain_core.messages import AIMessage
        class Model(FakeModel):
            def invoke(self, messages):
                if "Schema:" in messages[0].content:
                    return super().invoke(messages)
                return AIMessage(content="backup checkpoint reply")
        general_agent.llm = Model()
        with TestClient(app, headers=HEADERS) as c:
            c.post("/auth/register", json={"username": "backup_user", "password": "fictional-password-123"}).raise_for_status()
            c.post("/chat", json={"message": "你好", "mode": "chat"}).raise_for_status()
            for name in ("plan.txt", "change.md"):
                c.post("/documents", files={"file": (name, (FIXTURES/name).read_bytes())}).raise_for_status()
            payload = {"message": "计算剩余工期", "request_id": "repeat-test-0001"}
            first = c.post("/chat", json=payload).raise_for_status().json()
            history_before = c.get("/history").json()
            second = c.post("/chat", json=payload).raise_for_status().json()
            assert first == second
            assert c.get("/history").json() == history_before
            assert c.post("/chat", json={**payload, "message": "other"}).status_code == 409
            with app_db() as db:
                uid = db.execute("SELECT user_id FROM accounts").fetchone()[0]
            worker = subprocess.Popen([sys.executable, "-m", "tests.concurrency_backup_evaluation", tmp])
            try:
                for _ in range(100):
                    if (directory / "ready").exists():
                        break
                    time.sleep(.05)
                assert (directory / "ready").exists()
                try:
                    with operation("held-identity"):
                        raise AssertionError("concurrent identity lease allowed")
                except HTTPException as error:
                    assert error.status_code == 409
                try:
                    backup(directory / "busy-backup")
                    raise AssertionError("backup allowed during operation")
                except RuntimeError:
                    pass
                worker.wait(timeout=10)
            finally:
                if worker.poll() is None:
                    worker.terminate()
                    worker.wait()
            from src.server.schedule_tasks import save_task
            from src.memory.store import memory_store
            memory_store.save(uid, "name", "Snapshot User")
            pending = {**first["task"], "pending": "calculator", "status": "waiting"}
            pending.pop("result", None)
            save_task(uid, pending)
            from tests.vector_index_evaluation import FakeVectors, close_test_chroma
            from src.retrieval.service import IndexService, enqueue, statuses
            from src.server.documents import documents
            vectors = IndexService(backend_factory=FakeVectors)
            vector_file = documents(uid)[0]['id']
            enqueue(uid, vector_file)
            assert vectors.run_once()
            assert statuses(uid)[vector_file]['status'] == 'READY'
            snapshot = directory / "snapshot"
            backup(snapshot)
            try:
                restore(snapshot, True)
                raise AssertionError("live restore allowed")
            except RuntimeError:
                pass
        general_agent.conn.close()
        with app_db() as db:
            db.execute("DELETE FROM documents")
            db.execute("DELETE FROM agent_tasks")
        from unittest.mock import patch
        from src.server import backup as backup_module
        real_copy = backup_module.copy_database
        def fail_memory(source, destination):
            if Path(source) == snapshot / "memory.db":
                raise OSError("injected restore failure")
            return real_copy(source, destination)
        with patch.object(backup_module, "copy_database", side_effect=fail_memory):
            try:
                restore(snapshot, True)
                raise AssertionError("restore fault not injected")
            except OSError:
                pass
        assert not backup_module.restore_marker().exists()
        with app_db() as db:
            assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
        restore(snapshot, True)
        with app_db() as db:
            assert db.execute("SELECT username FROM accounts").fetchone()[0] == "backup_user"
            assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 2
            assert db.execute("SELECT count(*) FROM agent_tasks").fetchone()[0] == 1
            state = json.loads(db.execute("SELECT state FROM schedule_tasks").fetchone()[0])
            assert state["pending"] == "calculator" and "result" not in state
            assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM rag_indexes").fetchone()[0] == 0
        enqueue(uid, vector_file)
        assert vectors.run_once()
        assert vectors.search(uid, "项目计划", [vector_file])
        close_test_chroma()
        assert memory_store.get(uid, "name") == "Snapshot User"
        import sqlite3
        checkpoint = sqlite3.connect(config.CHECKPOINT_DB)
        try:
            assert checkpoint.execute("SELECT count(*) FROM checkpoints WHERE thread_id=?", (uid,)).fetchone()[0] > 0
        finally:
            checkpoint.close()
        class NoModel:
            def invoke(self, messages):
                raise AssertionError("restored task must reuse evidence")
        general_agent.llm = NoModel()
        with TestClient(app, headers=HEADERS) as restored:
            restored.post("/auth/login", json={"username": "backup_user", "password": "fictional-password-123"}).raise_for_status()
            completed = restored.post("/chat", json={"message": "继续任务"}).raise_for_status().json()
            assert "剩余 15" in completed["answer"] and completed["tool_calls"] == ["calculator"]
            assert completed["task"]["id"] == first["task"]["id"]
            citation = completed["citations"][0]
            assert restored.get("/documents/" + citation["file_id"]).status_code == 200
    print("PASS separate-process identity exclusion, idempotent chat, maintenance barrier, live-restore refusal and complete restore")


if __name__ == "__main__":
    child(sys.argv[1]) if len(sys.argv) > 1 else run()
