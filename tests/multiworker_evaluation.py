"""Temporary two-worker HTTP smoke with a local substitute model."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import httpx


def create_app():
    from src.server.api import app, general_agent
    from fastapi.routing import APIRoute
    from langchain_core.messages import AIMessage
    from tests.attachment_evaluation import FakeModel
    class Model(FakeModel):
        def invoke(self, messages):
            if "Schema:" in messages[0].content or "只解析" in messages[0].content:
                return super().invoke(messages)
            return AIMessage(content="multiworker response")
    general_agent.llm = Model()
    app.router.routes.insert(0, APIRoute("/worker-id", lambda: {"pid": os.getpid()}, methods=["GET"]))
    return app


def run():
    with tempfile.TemporaryDirectory() as tmp:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        env = {**os.environ, "MY_AGENT_MODE": "demo", "MY_AGENT_PUBLIC_ORIGIN": "https://demo.example",
               "MY_AGENT_DEMO_DATA_DIR": tmp, "MY_AGENT_OLLAMA_URL": "http://127.0.0.1:11434"}
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.multiworker_evaluation:create_app",
                                   "--factory", "--host", "127.0.0.1", "--port", str(port), "--workers", "2",
                                   "--log-level", "warning"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    if httpx.get(url + "/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            with httpx.Client(base_url=url, headers={"Origin": "https://demo.example", "Connection": "close"}, timeout=30) as c:
                c.post("/auth/register", json={"username": "worker_user", "password": "fictional-password-123"}).raise_for_status()
                # Secure cookies are deliberately forwarded for this loopback HTTP-only smoke.
                token = c.cookies.get("__Host-my_agent_session")
                c.headers["Cookie"] = "__Host-my_agent_session=" + token
                from tests.attachment_evaluation import FIXTURES
                for name in ("plan.txt", "change.md"):
                    c.post("/documents", files={"file": (name, (FIXTURES/name).read_bytes())}).raise_for_status()
                calculated = c.post("/chat", json={"message": "计算剩余工期"}).raise_for_status().json()
                assert "剩余 15" in calculated["answer"], calculated
                followed = c.post("/chat", json={"message": "第二阶段再延后一周呢"}).raise_for_status().json()
                assert "剩余 20" in followed["answer"]
                assert len(c.get("/tasks").json()["tasks"]) == 1
                pids = set()
                for _ in range(40):
                    pids.add(c.get("/worker-id").raise_for_status().json()["pid"])
                    payload = {"message": "你好", "mode": "chat", "request_id": str(uuid4())}
                    c.post("/chat", json=payload).raise_for_status()
                    if len(pids) >= 2:
                        break
                assert len(pids) == 2, pids
                assert len(c.get("/history").raise_for_status().json()["messages"]) >= 4
                assert c.get("/auth/me").json()["username"] == "worker_user"
                print("PASS two actual Uvicorn workers, shared login/history/checkpoint, pids", sorted(pids))
        finally:
            subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server.wait(timeout=10)
            time.sleep(.5)


if __name__ == "__main__":
    run()
