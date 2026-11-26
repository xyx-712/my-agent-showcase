"""Summary and multiple-task API acceptance."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from fastapi.testclient import TestClient
from tests.attachment_evaluation import FakeModel, HEADERS, FIXTURES


class SummaryModel(FakeModel):
    def invoke(self, messages):
        if "跨批次合并" in messages[0].content:
            return SimpleNamespace(content=json.dumps({"summary": "各批资料已归纳，版本分歧和数值需结合原文核对。"}, ensure_ascii=False))
        if "综合归纳" not in messages[0].content:
            return super().invoke(messages)
        data = json.loads(messages[-1].content)
        return SimpleNamespace(content=json.dumps({"items": [], "synthesis": [
            {"text": "资料包含原计划与后续变更，需以批准状态和替代关系核对适用版本。",
             "kind": "inference", "evidence": [{"source": i, "quote": source["text"]}
                                              for i, source in enumerate(data["sources"])]}
        ]}, ensure_ascii=False))


def run():
    with tempfile.TemporaryDirectory() as tmp:
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(tmp) / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = Path(tmp) / "history.json"
        from src.server.api import app, general_agent
        from src.agent.skills import answer_documents
        class UncitedDigest:
            def invoke(self, messages):
                return SimpleNamespace(content=json.dumps({"items": [], "synthesis": [], "digest": "无依据的断言"}))
        text, refs, digest = answer_documents(UncitedDigest(), [], "总结", return_digest=True)
        assert not refs and digest == text and "无依据的断言" not in digest
        general_agent.llm = SummaryModel()
        with TestClient(app, headers=HEADERS) as c, TestClient(app, headers=HEADERS) as other:
            for client in (c, other):
                client.post("/session", json={}).raise_for_status()
            assert c.post("/documents-demo", json={}).status_code == 404
            assert c.get("/documents").json()["files"] == []
            for name in ("plan.txt", "change.md"):
                c.post("/documents", files={"file": (name, (FIXTURES/name).read_bytes())}).raise_for_status()
            def chat(text):
                return c.post("/chat", json={"message": text}).raise_for_status().json()
            summary = chat("对比总结文件变更")
            assert "[推断" in summary["answer"] and len(summary["citations"]) == 2
            first_id = summary["task"]["id"]
            task2 = c.post("/tasks/new", json={"name": "工期任务"}).raise_for_status().json()["id"]
            calc = chat("计算剩余工期")
            assert calc["task"]["id"] == task2 and "剩余 15" in calc["answer"], calc
            assert len(c.get("/tasks").json()["tasks"]) == 2
            stale = c.post("/chat", json={"message": "继续任务", "task_id": first_id})
            assert stale.status_code == 409
            assert c.get("/task").json()["id"] == task2
            assert other.post("/tasks/select", json={"id": task2}).status_code == 404
            c.post("/tasks/select", json={"id": first_id}).raise_for_status()
            resumed = chat("继续任务")
            assert resumed["task"]["id"] == first_id and resumed["answer"] == summary["answer"]
            c.post("/tasks/select", json={"id": task2}).raise_for_status()
            assert "剩余 20" in chat("第二阶段再延后一周呢")["answer"]
            c.post("/tasks/pause", json={}).raise_for_status()
            assert c.get("/task").json()["status"] == "paused"
            assert "剩余 20" in chat("继续任务")["answer"]
            long_text = "\n".join(f"独立资料第 {i} 行，版本记录与待核对事项。" for i in range(700))
            c.post("/documents", files={"file": ("long.txt", long_text.encode())}).raise_for_status()
            grouped = chat("总结所有文件")
            for _ in range(10):
                if grouped["task"].get("status") == "completed":
                    break
                assert grouped["task"]["pending"] == "continue"
                grouped = chat("继续任务")
            assert grouped["task"]["status"] == "completed"
            assert grouped["task"]["qa_offset"] == len(grouped["task"]["sources"])
            assert len(grouped["citations"]) > 24
            assert "[跨批次综合" in grouped["answer"]
            from src.server.schedule_tasks import save_task
            from src.server.session import app_db
            from src.tools.document_search import search_documents
            with app_db() as db:
                owner = db.execute("SELECT user_id FROM documents LIMIT 1").fetchone()[0]
            save_task(owner, {"id": "legacy-task", "project": "星港", "delay": 0, "version": None,
                              "sections": search_documents("星港"), "result": 15})
            legacy = chat("继续任务")
            general_agent.conn.close()
            assert legacy["task"]["id"] == "legacy-task" and "内置演示资料已停用" in legacy["answer"], legacy.get("answer", "")[:300]


        general_agent.conn.close()
    print("PASS cited synthesis, multiple tasks, alternating followups, pause/resume and task isolation")


if __name__ == "__main__":
    run()
