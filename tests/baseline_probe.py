"""Repeatable pre-change API probe. Run against revision 3fd825b."""
import contextlib
import io
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

ASK = "按最新变更算出剩余工期，并标注依据"
FOLLOW = "第二阶段再延后一周呢"
FALSE_TRIGGER = "你知道多少种颜色"
MISSING = "按月桥项目最新变更算出剩余工期"
CONFLICT = "按双轨项目最新变更算出剩余工期"


def run():
    with tempfile.TemporaryDirectory() as directory:
        import src.config as config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(directory) / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = Path(directory) / "history.json"
        from src.server.api import app
        from src.agent import graph as workflow

        seen = []
        def reply(messages):
            seen.append([message.type for message in messages])
            return SimpleNamespace(content="离线固定回复")

        workflow.llm = SimpleNamespace(invoke=reply)
        try:
            headers = {"Origin": "http://127.0.0.1:5173"}
            with TestClient(app, headers=headers) as first, TestClient(app, headers=headers) as second:
                for client in (first, second):
                    assert client.post("/session", json={}).is_success
                for name, client, prompt in [
                    ("initial", first, ASK), ("followup", first, FOLLOW),
                    ("false_trigger", first, FALSE_TRIGGER), ("missing", first, MISSING),
                    ("conflict", first, CONFLICT), ("isolation", second, FOLLOW),
                ]:
                    start = time.perf_counter()
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = client.post("/chat", json={"message": prompt})
                    assert result.is_success
                    data = result.json()
                    print(name, round((time.perf_counter() - start) * 1000, 1),
                          data["tool"] or "-", data["tool_result"], seen[-1])
                assert len(second.get("/history").json()["messages"]) == 2
                assert len(first.get("/history").json()["messages"]) == 10
        finally:
            workflow.conn.close()


if __name__ == "__main__":
    run()
