"""Exercise natural-language DAG extraction through the normal HTTP chat entry."""
from pathlib import Path
import json
import tempfile
import time

from fastapi.testclient import TestClient
from types import SimpleNamespace
from tests.attachment_evaluation import FakeModel, HEADERS

TEXT = """星港项目版本 V1，2026-04-06 已批准，替代关系为无。
统计日期为2026-04-10，口径为剩余工作日。
第一阶段剩余二个工作日，依赖为无。
第二阶段剩余五个工作日，依赖为第一阶段。
第三阶段剩余三个工作日，依赖为第一阶段。"""


class NetworkModel(FakeModel):
    def invoke(self, messages):
        if "提取每个版本" not in messages[0].content:
            return super().invoke(messages)
        sources = json.loads(messages[-1].content)
        quote = sources[0]["text"]
        def fact(value):
            return {"value": value, "quote": quote}
        record = {key: fact(value) for key, value in {
            "project": "星港", "version": "V1", "published": "2026-04-06", "status": "已批准",
            "replaces": "无", "as_of": "2026-04-10", "basis": "剩余工作日",
        }.items()}
        record["stages"] = [
            {"source": 0, "name": fact(name), "remaining": fact(days), "dependencies": fact(deps),
             "as_of": fact("2026-04-10")}
            for name, days, deps in [("第一阶段", "二", "无"), ("第二阶段", "五", "第一阶段"), ("第三阶段", "三", "第一阶段")]
        ]
        return SimpleNamespace(content=json.dumps({"records": [{"source": 0, **record}], "missing": []}, ensure_ascii=False))


def run(real=False):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(directory) / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = Path(directory) / "history.json"
        if real:
            import os
            os.environ["MY_AGENT_MODEL"] = "qwen2.5:7b"
            os.environ["MY_AGENT_OLLAMA_URL"] = "http://127.0.0.1:11434"
            os.environ.pop("MY_AGENT_OLLAMA_API_KEY", None)
        from src.server.api import app, general_agent
        if not real:
            general_agent.llm = NetworkModel()
        with TestClient(app, headers=HEADERS) as c:
            c.post("/session", json={}).raise_for_status()
            c.post("/documents", files={"file": ("network.txt", TEXT.encode())}).raise_for_status()
            def chat(text, **extra):
                return c.post("/chat", json={"message": text, **extra}).raise_for_status().json()
            c.post("/tasks/new", json={"name": "日历回归"}).raise_for_status()
            result = chat("计算剩余工期", calendar={"start": "2026-04-10", "weekdays": [0,1,2,3,4],
                                                   "holidays": ["2026-04-13"], "workdays": ["2026-04-11"]})
            if "剩余 7" not in result["answer"]:
                general_agent.conn.close()
                raise AssertionError(result)
            assert "第一阶段 → 第二阶段" in result["answer"]
            assert "完成日期" in result["answer"]
            assert result["task"]["calendar"]["workdays"] == ["2026-04-11"]
            assert "增加任务时长" in chat("第二阶段再延后一周呢")["answer"]
            result = chat("增加时长")
            assert "剩余 12" in result["answer"], result
            if not real:
                import os
                os.environ["MY_AGENT_FAIL_CALCULATOR_ONCE"] = "1"
                try:
                    failure = chat("计算剩余工期")
                    assert "临时故障" in failure["answer"]
                    class NoModel:
                        def invoke(self, messages):
                            raise AssertionError("resume should reuse evidence")
                    general_agent.llm = NoModel()
                    resumed = chat("继续任务")
                    assert "剩余 7" in resumed["answer"]
                    assert resumed["tool_calls"] == ["project_schedule"]
                finally:
                    os.environ.pop("MY_AGENT_FAIL_CALCULATOR_ONCE", None)

        general_agent.conn.close()
    print("PASS uploaded Chinese-number parallel DAG, calendar, ambiguous delay and continuation", "real" if real else "offline", round(time.perf_counter() - started, 3), "seconds")


if __name__ == "__main__":
    import sys
    run("--ollama" in sys.argv)
