"""Regression: uploaded files must not capture ordinary chat or arithmetic."""
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tests.attachment_evaluation import FakeModel, FIXTURES, HEADERS


class Model(FakeModel):
    def invoke(self, messages):
        prompt = messages[0].content
        if "判断最后一条消息" in prompt:
            text = json.loads(messages[-1].content)["messages"][-1]["content"]
            return AIMessage(content=json.dumps({"route": "documents" if "她有哪些经历" in text else "chat"}))
        if "Schema:" not in prompt and "只解析" not in prompt:
            return AIMessage(content="普通聊天回复")
        return super().invoke(messages)


def run():
    with tempfile.TemporaryDirectory() as directory:
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(directory) / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = Path(directory) / "history.json"
        from src.server.api import app, general_agent
        general_agent.llm = Model()
        try:
            with TestClient(app, headers=HEADERS) as c:
                c.post("/session", json={}).raise_for_status()
                for name in ("plan.txt", "change.md"):
                    c.post("/documents", files={"file": (name, (FIXTURES/name).read_bytes())}).raise_for_status()
                def send(message, mode="auto"):
                    return c.post("/chat", json={"message": message, "mode": mode}).raise_for_status().json()
                first = send("计算剩余工期")
                assert "剩余 15" in first["answer"], first
                before = c.get("/task").json()
                for text in ("你好，请介绍一下你自己。", "1+4=?", "什么是递归？"):
                    result = send(text)
                    assert "当前资料中找不到" not in result["answer"]
                    assert not result.get("citations")
                    if text == "1+4=?":
                        assert result["tool"] == "calculator"
                        assert "'result': 5" in result["tool_result"]
                    assert c.get("/task").json() == before
                result = send("总结文件", "chat")
                assert result["answer"] == "普通聊天回复"
                assert c.get("/task").json() == before
                assert "剩余 20" in send("第二阶段再延后一周呢")["answer"]
                assert send("她有哪些经历")["tool_calls"] == ["document_search"]
                assert send("总结文件", "documents")["citations"]
                assert c.post("/chat", json={"message": "x", "mode": "shell"}).status_code == 422
        finally:
            general_agent.conn.close()
    print("PASS uploaded attachments + ordinary chat + arithmetic + task preservation + modes")


if __name__ == "__main__":
    run()
