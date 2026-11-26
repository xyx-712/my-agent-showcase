"""Temporary API test of shared model injection and message assembly."""
from pathlib import Path
import os
import sys
import tempfile
import time

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tests.attachment_evaluation import FakeModel, FIXTURES, HEADERS


def run(real=False):
    if real:
        os.environ["MY_AGENT_MODEL"] = "qwen2.5:7b"
        os.environ["MY_AGENT_OLLAMA_URL"] = "http://127.0.0.1:11434"
        os.environ.pop("MY_AGENT_OLLAMA_API_KEY", None)
    with tempfile.TemporaryDirectory() as directory:
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(directory) / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = Path(directory) / "history.json"
        from src.server.api import app, general_agent
        from src.agent.skills import Action, model_json
        from src.agent.model_provider import get_chat_model

        if real:
            started = time.perf_counter()
            try:
                with TestClient(app, headers=HEADERS) as c:
                    c.post("/session", json={}).raise_for_status()
                    for message in ("这轮测试的代号是蓝杉。请只回复：已收到。", "这轮测试的代号是什么？"):
                        result = c.post("/chat", json={"message": message, "mode": "chat"}).raise_for_status().json()
                        print(result["answer"], flush=True)
                    assert "蓝杉" in result["answer"], result["answer"]
                    assert len(c.get("/history").json()["messages"]) == 4
                print("PASS real Ollama templated multi-turn chat", round(time.perf_counter() - started, 3), "seconds")
            finally:
                general_agent.conn.close()
            return

        class Model(FakeModel):
            def __init__(self):
                self.calls = []
            def invoke(self, messages):
                self.calls.append(messages)
                if "Schema:" in messages[0].content:
                    return super().invoke(messages)
                return AIMessage(content="isolated reply")

        assert general_agent.llm is get_chat_model()
        model = Model()
        general_agent.llm = model
        try:
            with TestClient(app, headers=HEADERS) as c:
                c.post("/session", json={}).raise_for_status()
                for message in ("first-message-token", "second-message-{token}"):
                    c.post("/chat", json={"message": message, "mode": "chat"}).raise_for_status()
                    call = model.calls[-1]
                    assert sum(m.type == "human" and m.content == message for m in call) == 1
                assert [(m.type, m.content) for m in model.calls[-1][1:]] == [
                    ("human", "first-message-token"), ("ai", "isolated reply"), ("human", "second-message-{token}")]
                c.post("/chat", json={"message": "1+4=?", "mode": "chat"}).raise_for_status()
                assert "计算结果：5" in c.get("/history").json()["messages"][-1]["content"]
                multiple = c.post("/chat", json={"message": "1+4; 2+6", "mode": "chat"}).raise_for_status().json()
                assert "'result': 5" in multiple["tool_result"] and "'result': 8" in multiple["tool_result"]
                normal = c.post("/chat", json={"message": "你好", "mode": "chat"}).raise_for_status().json()
                assert not normal["tool_result"], "previous tool batch must not leak into the next turn"
                for name in ("plan.txt", "change.md"):
                    c.post("/documents", files={"file": (name, (FIXTURES/name).read_bytes())}).raise_for_status()
                result = c.post("/chat", json={"message": "计算剩余工期", "mode": "documents"}).raise_for_status().json()
                assert "剩余 15" in result["answer"] and result["citations"]
                assert any("选择 document_qa" in call[0].content for call in model.calls)

            class BadThenGood(Model):
                def invoke(self, messages):
                    self.calls.append(messages)
                    return AIMessage(content="bad-json" if len(self.calls) == 1 else '{"skill":"document_qa","tool":"document_search","query":"资料"}')
            retry = BadThenGood()
            assert model_json(retry, Action, "test", {"request": "{text}"}).skill == "document_qa"
            assert len(retry.calls) == 2 and "上次输出无效" in retry.calls[1][0].content
            class AlwaysBad(Model):
                def invoke(self, messages):
                    self.calls.append(messages)
                    return AIMessage(content="bad-json")
            exhausted = AlwaysBad()
            try:
                model_json(exhausted, Action, "test", {})
                raise AssertionError("invalid structured output accepted")
            except ValueError:
                assert len(exhausted.calls) == 2
        finally:
            general_agent.conn.close()
    print("PASS API model injection, roles/history/current message once, tool prompt, shared document calls and bounded retry")


if __name__ == "__main__":
    run("--ollama" in sys.argv)
