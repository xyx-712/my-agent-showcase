"""Isolated abstract/referencing regression; --ollama uses real local inference."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
from tests.attachment_evaluation import FakeModel, HEADERS


def pdf(lines):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 12 Tf 40 740 Td 16 TL " + " ".join("(" + line + ") Tj T*" for line in lines) + " ET").encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class Model(FakeModel):
    fail = False
    fail_after = None
    batches = 0
    def invoke(self, messages):
        if "跨批次合并" in messages[0].content:
            return SimpleNamespace(content=json.dumps({"summary": "各批资料已汇总，结论需结合原文核对。"}, ensure_ascii=False))
        if "综合归纳" not in messages[0].content:
            return super().invoke(messages)
        data = json.loads(messages[-1].content)
        assert all(s["source"] == i and "index" not in s for i, s in enumerate(data["sources"]))
        self.batches += 1
        if self.fail or (self.fail_after is not None and self.batches > self.fail_after):
            return SimpleNamespace(content=json.dumps({"items": [{"source": 999, "quote": "fabricated proof"}]}))
        return SimpleNamespace(content=json.dumps({"synthesis": [{"text": "研究实现本地文档助手，并通过引用验证提高可核对性。", "kind": "fact", "evidence": [{"source": i, "quote": s["text"]} for i, s in enumerate(data["sources"])]}]} ,ensure_ascii=False))


def setup(directory):
    from src import config
    for name in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
        setattr(config, name, directory / (name + ".db"))
    from src.server import history
    history.HISTORY_FILE = directory / "history.json"
    from src.server.api import app, general_agent
    return app, general_agent


def run(real=False, resume=None):
    os.environ["MY_AGENT_MODE"] = "local"
    os.environ["MY_AGENT_MODEL"] = "qwen2.5:7b"
    os.environ["MY_AGENT_OLLAMA_URL"] = "http://127.0.0.1:11434"
    os.environ.pop("MY_AGENT_OLLAMA_API_KEY", None)
    started = time.perf_counter()
    if resume:
        app, agent = setup(Path(resume))
        agent.llm = Model()
        from src.server.session import COOKIE_NAME
        try:
            with TestClient(app, headers=HEADERS) as c:
                c.cookies.set(COOKIE_NAME, (Path(resume)/"cookie").read_text())
                r = c.post("/chat", json={"message": "继续任务", "mode": "documents"}).raise_for_status().json()
                assert r["task"]["status"] == "completed", r["answer"]
                assert r["task"]["id"] == (Path(resume)/"task").read_text()
                assert "document_search" not in r["tool_calls"]
                assert r["citations"]
                assert agent.llm.batches == 1, "completed first batch must not run again"
            print("PASS fresh-process abstract resume reuses persisted sources")
        finally:
            agent.conn.close()
        return
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        app, agent = setup(directory)
        model = Model()
        if not real:
            agent.llm = model
        try:
            from src.agent.skills import answer_documents
            if not real:
                source = {"index": 40, "name": "fiction.txt", "text": "original unique evidence", "page": None, "start": 8, "end": 8}
                class Reply:
                    def __init__(self, index, quote): self.index, self.quote = index, quote
                    def invoke(self, messages):
                        return SimpleNamespace(content=json.dumps({"items": [{"source": self.index, "quote": self.quote}]}))
                _, refs = answer_documents(Reply(40, source["text"]), [source], "问答")
                assert refs == [source]
                _, refs = answer_documents(Reply(1, source["text"]), [source, {**source, "text": "other evidence"}], "问答")
                assert refs == [source]
                for index, quote, sources in [(-1, source["text"], [source]), ("0", source["text"], [source]), (9, source["text"], [source, source]), (0, "original unique evidence.", [source]), (9, "fabricated", [source])]:
                    try:
                        answer_documents(Reply(index, quote), sources, "问答")
                        raise AssertionError("invalid evidence accepted")
                    except ValueError:
                        pass
            with TestClient(app, headers=HEADERS) as c, TestClient(app, headers=HEADERS) as other:
                for client in (c, other): client.post("/session", json={}).raise_for_status()
                body = pdf(["A local document assistant", "Abstract", "We build a local assistant for document analysis.", "It uses evidence validation and preserves page references.", "The system helps users check answers against original documents.", "Keywords: local assistant, evidence", "Introduction", "SECRET_BODY_ONLY does not belong to the abstract."])
                upload = c.post("/documents", files={"file": ("fiction.pdf", body)}).raise_for_status().json()
                assert other.get("/documents/" + upload["id"]).status_code == 404
                def chat(text):
                    return c.post("/chat", json={"message": text, "mode": "documents"}).raise_for_status().json()
                result = chat("将文件中的摘要部分，为我缩减一些")
                assert result["task"]["status"] == "completed", result["answer"]
                assert result["citations"] and result["citations"][0]["page"] == 1
                assert all("SECRET_BODY_ONLY" not in s["text"] for s in result["task"]["sources"])
                assert "[原文事实]" in result["answer"], result["answer"]
                if real:
                    print(result["answer"], flush=True)
                    print("PASS real PDF abstract rewrite with verified page/line citations", round(time.perf_counter()-started,3), "seconds")
                    return
                from src.server.schedule_tasks import save_task
                from src.server.session import app_db
                with app_db() as db:
                    owner = db.execute("SELECT user_id FROM documents WHERE id=?", (upload["id"],)).fetchone()[0]
                old = {**result["task"], "status": "waiting", "pending": "continue", "qa_parts": ["OLD_UNSCOPED_RESULT"], "qa_offset": 0}
                old.pop("abstract_scope", None)
                old.pop("abstract_label", None)
                save_task(owner, old)
                upgraded = chat("继续任务")
                assert upgraded["task"]["id"] == result["task"]["id"]
                assert "OLD_UNSCOPED_RESULT" not in upgraded["answer"]
                assert upgraded["task"]["abstract_scope"]
                c.post("/documents", files={"file": ("second.pdf", body)}).raise_for_status()
                choice = chat("缩减文件中的摘要")
                assert choice["task"]["pending"] == "abstract_choice"
                chosen = chat("选择摘要 2")
                assert chosen["task"]["id"] == choice["task"]["id"] and chosen["task"]["status"] == "completed"
                assert chosen["citations"][0]["name"] == "second.pdf"
                assert other.post("/tasks/select", json={"id": chosen["task"]["id"]}).status_code == 404
                for file in c.get("/documents").json()["files"]:
                    c.delete("/documents/" + file["id"]).raise_for_status()
                c.post("/documents", files={"file": ("plain.txt", b"No labeled abstract here, just ordinary body text.")}).raise_for_status()
                missing = chat("缩减摘要")
                assert missing["task"]["pending"] == "abstract"
                c.post("/documents", files={"file": ("supplied.md", "# 摘要\n这是补充的摘要正文。".encode())}).raise_for_status()
                chat("继续任务")
                assert chat("继续任务")["task"]["status"] == "completed"
                for file in c.get("/documents").json()["files"]:
                    c.delete("/documents/" + file["id"]).raise_for_status()
                # 5 batches, with an original chunk index different from each batch's numbering.
                c.post("/documents", files={"file": ("long.txt", "\n".join(f"记录{i}内容，核对原文。" for i in range(330)).encode())}).raise_for_status()
                r = chat("总结所有文件")
                for _ in range(10):
                    if r["task"]["status"] == "completed": break
                    r = chat("继续任务")
                assert r["task"]["status"] == "completed" and len(r["citations"]) > 4
                for file in c.get("/documents").json()["files"]:
                    c.delete("/documents/" + file["id"]).raise_for_status()
                long_abstract = "# 摘要\n" + "\n".join(f"摘要第{i}行独立证据。" for i in range(95)) + "\n# 引言\n正文不属于摘要。"
                c.post("/documents", files={"file": ("retry.md", long_abstract.encode())}).raise_for_status()
                model.batches = 0
                model.fail_after = 1
                failed = chat("缩减摘要")
                assert "格式或引用校验" in failed["answer"] and "补充明确资料" not in failed["answer"]
                assert failed["task"].get("qa_offset", 0) == 4
                from src.server.session import COOKIE_NAME
                (directory/"cookie").write_text(c.cookies[COOKIE_NAME])
                (directory/"task").write_text(failed["task"]["id"])
            child = subprocess.run([sys.executable, "-X", "utf8", "-m", "tests.abstract_evaluation", "--resume", tmp], capture_output=True, text=True, encoding="utf-8", timeout=60)
            assert child.returncode == 0, child.stdout + child.stderr
            print(child.stdout.strip())
            print("PASS explicit batch IDs, invalid/ambiguous evidence, abstract selection, missing/supplied abstract, isolation and cross-batch continuation")
        finally:
            agent.conn.close()


if __name__ == "__main__":
    run("--ollama" in sys.argv, sys.argv[sys.argv.index("--resume")+1] if "--resume" in sys.argv else None)
