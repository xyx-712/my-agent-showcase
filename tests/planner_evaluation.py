"""Actual API and persisted LangGraph Planner acceptance with fictional isolated data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from langchain_core.messages import AIMessage
from fastapi.testclient import TestClient
from tests.attachment_evaluation import FakeModel, HEADERS
from tests.test_planner import plan, step


class PlanningModel(FakeModel):
    def __init__(self):
        self.plans = 0
        self.answers = []
    def invoke(self, messages):
        if "规划普通聊天任务" in messages[0].content:
            self.plans += 1
            text = json.loads(messages[-1].content)["messages"][-1]["content"]
            result = {"action": "chat", "steps": [], "question": ""}
            if "先计算" in text:
                result = plan(step(1, "100+200"), step(2, "$s1.result * 3", ["s1"]))
            elif "独立计算" in text:
                result = plan(step(1, "10+20"), step(2, "2+3"))
            elif "顺序三步" in text:
                result = plan(step(1, "1+2"), step(2, "$s1.result*3", ["s1"]), step(3, "$s2.result+1", ["s2"]))
            elif "时间并计算" in text:
                result = plan({"id": "s1", "order": 1, "task_type": "time_query", "tool": "time", "args": {}, "depends_on": []}, step(2, "2+3"))
            elif "参数错误" in text:
                result = plan({**step(1, "1+2"), "args": {}})
            elif "失败依赖" in text:
                result = plan(step(1, "1/0"), step(2, "$s1.result*3", ["s1"]))
            elif "超限" in text:
                result = plan(*(step(i, "1+2") for i in range(1, 10)))
            elif "缺少参数" in text:
                result = {"action": "clarify", "steps": [], "question": "请提供要计算的数值。"}
            elif "恶意文件" in text:
                result = plan({"id": "s1", "order": 1, "task_type": "time_query", "tool": "file_reader", "args": {"path": "C:/secret.txt"}, "depends_on": []})
            return AIMessage(content=json.dumps(result, ensure_ascii=False))
        if "Schema:" in messages[0].content:
            return super().invoke(messages)
        self.answers.append(messages)
        return AIMessage(content="普通聊天回复" if messages[-1].type != "tool" else "已根据工具结果完成回答。")


def run(real=False):
    os.environ["MY_AGENT_MODE"] = "local"
    if real:
        os.environ["MY_AGENT_MODEL"] = "qwen2.5:7b"
        os.environ["MY_AGENT_OLLAMA_URL"] = "http://127.0.0.1:11434"
        os.environ.pop("MY_AGENT_OLLAMA_API_KEY", None)
    with tempfile.TemporaryDirectory() as tmp:
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(tmp)/(field+".db"))
        from src.server import history
        history.HISTORY_FILE = Path(tmp)/"history.json"
        from src.server.api import app, general_agent
        from src.server.session import app_db, hash_token, COOKIE_NAME
        model = PlanningModel()
        if not real:
            general_agent.llm = model
        try:
            with TestClient(app, headers=HEADERS) as c:
                c.post("/session", json={}).raise_for_status()
                with app_db() as db:
                    owner = db.execute("SELECT user_id FROM sessions WHERE token_hash=?", (hash_token(c.cookies[COOKIE_NAME]),)).fetchone()[0]
                thread = {"configurable": {"thread_id": owner}}
                def chat(text):
                    response = c.post("/chat", json={"message": text, "mode": "chat"}).raise_for_status().json()
                    state = general_agent.graph.get_state(thread).values
                    return response, state
                started = time.perf_counter()
                result, state = chat("先计算100+200，再将结果乘以3。")
                assert "900" in result["answer"], result
                records = state["execution_records"]
                assert len(records) == 2 and records[0]["result"]["result"] == 300
                assert records[1]["result"]["result"] == 900
                first_id = state["plan"]["steps"][0]["id"]
                assert "$" + first_id + ".result" in state["plan"]["steps"][1]["args"]["expression"]
                assert first_id in state["plan"]["steps"][1]["depends_on"]
                assert "$" not in records[1]["args"]["expression"]
                assert len(state["execution_messages"]) == 4
                print(result["answer"], flush=True)
                print("PASS", "real Ollama" if real else "substitute", "structured dependency plan 300 -> 900", round(time.perf_counter()-started,3), "seconds")
                if real:
                    if '--trace' in sys.argv:
                        from langchain_core.callbacks import BaseCallbackHandler
                        class Trace(BaseCallbackHandler):
                            def on_llm_end(self,response,**kwargs):print('FICTIONAL_MODEL_OUTPUT',response.generations[0][0].text,flush=True)
                        general_agent.llm=general_agent.llm.model_copy(update={'callbacks':[Trace()]})
                    started = time.perf_counter()
                    result, state = chat("查询当前时间，并计算2+3。")
                    assert all(r.get('status')=='completed' for r in state['execution_records']), (result,state['plan'],state['execution_records'])
                    assert {r.get("tool") for r in state["execution_records"]} == {"time", "calculator"}, result
                    assert all(r["status"] == "completed" for r in state["execution_records"])
                    assert result["answer"] and not state["execution_error"]
                    print("PASS real Ollama mixed tools and ToolMessage answer", round(time.perf_counter()-started,3), "seconds", flush=True)
                    started = time.perf_counter()
                    result, state = chat("你好，请介绍一下你自己。")
                    assert state["plan"]["action"] == "chat" and not state["execution_records"]
                    print("PASS real Ollama ordinary chat without tools", round(time.perf_counter()-started,3), "seconds", flush=True)
                    return
                with TestClient(app, headers=HEADERS) as other:
                    other.post("/session", json={}).raise_for_status()
                    other_result = other.post("/chat", json={"message": "普通闲聊", "mode": "chat"}).raise_for_status().json()
                    assert not other_result["tool_result"]
                    assert all("900" not in m["content"] for m in other.get("/history").json()["messages"])
                    assert general_agent.graph.get_state(thread).values["execution_records"] == records
                result, state = chat("独立计算两道题")
                assert [r["result"]["result"] for r in state["execution_records"]] == [30, 5]
                result, state = chat("顺序三步")
                assert state["execution_records"][-1]["result"]["result"] == 10
                result, state = chat("查询时间并计算")
                assert [r["tool"] for r in state["execution_records"]] == ["time", "calculator"]
                rendered = model.answers[-1]
                assert [m.type for m in rendered][-4:] == ["ai", "tool", "ai", "tool"]
                assert not any(m.type == "system" and state["tool_result"] in m.content for m in rendered)
                for text in ("参数错误", "超限", "恶意文件"):
                    before = model.plans
                    result, state = chat(text)
                    assert "未执行任何工具" in result["answer"]
                    assert model.plans-before == 2
                    assert not state["execution_records"] and not state["execution_messages"]
                result, state = chat("失败依赖")
                assert "失败" in result["answer"]
                assert [r["status"] for r in state["execution_records"]] == ["failed", "skipped"]
                result, state = chat("缺少参数")
                assert "请提供" in result["answer"] and not state["execution_records"]
                result, state = chat("普通闲聊")
                assert result["answer"] == "普通聊天回复"
                assert not state["execution_records"] and not result["tool_result"]
                result, state = chat("1+4=?")
                assert "计算结果：5" in result["answer"] and len(state["execution_records"]) == 1
                result, state = chat(";".join("1+2" for _ in range(8)))
                assert len(state["execution_records"]) == 8 and not state["execution_error"]
                result, state = chat(";".join("1+2" for _ in range(9)))
                assert "未执行任何工具" in result["answer"]
            print("PASS actual LangGraph plans, dependencies, ToolMessage pairs, finite loop, error/clarification, bound and per-turn reset")
        finally:
            general_agent.conn.close()


if __name__ == "__main__":
    run("--ollama" in sys.argv)
