"""Real local Ollama cross-batch summary acceptance; isolated fictional files."""
import os
from pathlib import Path
import tempfile
import time

from fastapi.testclient import TestClient


def run():
    os.environ["MY_AGENT_MODEL"] = "qwen2.5:7b"
    os.environ["MY_AGENT_OLLAMA_URL"] = "http://127.0.0.1:11434"
    os.environ.pop("MY_AGENT_OLLAMA_API_KEY", None)
    started = time.perf_counter()
    from src import config
    with tempfile.TemporaryDirectory() as directory:
        for name in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, name, Path(directory) / (name + ".db"))
        from src.server import history
        history.HISTORY_FILE = Path(directory) / "history.json"
        from src.server.api import app, general_agent
        try:
            with TestClient(app, headers={"Origin": "http://127.0.0.1:5173"}) as client:
                client.post("/session", json={}).raise_for_status()
                for index in range(5):
                    text = f"海岚项目第{index + 1}份记录：界面模块已完成审核。\n记录日期为2026年4月10日。"
                    client.post("/documents", files={"file": (f"record-{index}.txt", text.encode())}).raise_for_status()
                for message in ("总结所有文件中的主要事实", "继续任务", "继续任务"):
                    result = client.post("/chat", json={"message": message, "mode": "documents"}).raise_for_status().json()
                    if result["task"]["status"] == "completed" or result["task"].get("pending") != "continue":
                        break
                assert result["task"]["status"] == "completed", result["answer"]
                assert "cross_batch_merge" in result["task"]["completed"]
                assert len(result["citations"]) == 5
        finally:
            general_agent.conn.close()
    print("PASS real Ollama five-file cross-batch summary and citations", round(time.perf_counter() - started, 3), "seconds")


if __name__ == "__main__":
    run()
