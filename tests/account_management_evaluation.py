"""Local mail substitute and account-management acceptance."""
from pathlib import Path
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.attachment_evaluation import HEADERS


def run():
    with tempfile.TemporaryDirectory() as tmp:
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(tmp) / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = Path(tmp) / "history.json"
        from src.server.api import app, general_agent
        from src.server import auth, account_management as ops
        from src.server.session import app_db, hash_token
        outbox = []
        with TestClient(app, headers=HEADERS) as a, TestClient(app, headers=HEADERS) as b:
            credentials = {"username": "mail_user", "password": "initial-password-123"}
            a.post("/auth/register", json=credentials).raise_for_status()
            b.post("/auth/login", json=credentials).raise_for_status()
            sessions = a.get("/auth/sessions").json()["sessions"]
            assert len(sessions) == 2
            other = next(s for s in sessions if not s["current"])
            a.post("/auth/sessions/revoke", json={"id": other["id"]}).raise_for_status()
            assert b.get("/history").status_code == 401
            b.post("/auth/login", json=credentials).raise_for_status()
            a.post("/auth/password/change", json={"current_password": credentials["password"], "new_password": "replacement-password-456"}).raise_for_status()
            assert b.get("/history").status_code == 401
            assert a.get("/auth/me").json()["kind"] == "account"
            auth.attempts.clear()
            with patch.object(ops, "deliver", side_effect=lambda email, subject, token: outbox.append((email, subject, token))):
                a.post("/auth/email/request", json={"email": "fiction@example.test", "current_password": "replacement-password-456"}).raise_for_status()
                proof = outbox[-1][2]
                with app_db() as db:
                    assert db.execute("SELECT token_hash FROM account_tokens").fetchone()[0] == hash_token(proof)
                a.post("/auth/email/verify", json={"token": proof}).raise_for_status()
                assert a.post("/auth/email/verify", json={"token": proof}).status_code == 400
                known = b.post("/auth/password/forgot", json={"email": "fiction@example.test"}).json()
                unknown = b.post("/auth/password/forgot", json={"email": "missing@example.test"}).json()
                assert known == unknown
                token = outbox[-1][2]
                b.post("/auth/password/reset", json={"token": token, "new_password": "reset-password-789"}).raise_for_status()
                assert a.get("/history").status_code == 401
                assert b.post("/auth/password/reset", json={"token": token, "new_password": "reset-password-789"}).status_code == 400
            auth.attempts.clear()
            b.post("/auth/login", json={"username": "mail_user", "password": "reset-password-789"}).raise_for_status()
            b.post("/auth/logout-all", json={}).raise_for_status()
            assert b.get("/history").status_code == 401
        general_agent.conn.close()
    print("PASS password change, device revoke, logout all, verified email, local mail substitute, single-use reset")


if __name__ == "__main__":
    run()
