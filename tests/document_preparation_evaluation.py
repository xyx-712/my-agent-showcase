"""API regression for document preparation using fictional files and temporary storage."""
from pathlib import Path
import tempfile
from copy import deepcopy
from fastapi.testclient import TestClient
from tests.attachment_evaluation import HEADERS
from tests.abstract_evaluation import Model


def run():
    with tempfile.TemporaryDirectory() as directory:
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, Path(directory)/(field+".db"))
        from src.server import history
        history.HISTORY_FILE=Path(directory)/"history.json"
        from src.server.api import app, general_agent
        from tests.test_retrieval_documents import docx_bytes
        from src.server import session
        assert session.APP_DB.resolve().is_relative_to(Path(directory).resolve()), "test database must be isolated"
        from src.server.documents import get_document, MAX_FILES
        from src.retrieval.loaders import load_owned_document
        from src.retrieval.splitter import split_documents
        from src.server.session import app_db
        general_agent.llm = Model()
        try:
            with TestClient(app, headers=HEADERS) as c, TestClient(app, headers=HEADERS) as other:
                for client in (c, other): client.post("/session", json={}).raise_for_status()
                body=docx_bytes()
                uploaded=c.post("/documents",files={"file":("fiction.docx",body)}).raise_for_status().json()
                identity=uploaded["id"]
                with app_db() as db:
                    owner=db.execute("SELECT user_id FROM documents WHERE id=?",(identity,)).fetchone()[0]
                original=deepcopy(get_document(owner,identity))
                children=split_documents(load_owned_document(owner,identity),15,3)
                assert children and get_document(owner,identity)==original
                try:
                    load_owned_document("different-user",identity)
                    raise AssertionError("unauthorized loader read")
                except Exception as error:
                    assert getattr(error,"status_code",None)==404
                result=c.post("/chat",json={"message":"总结所有文件","mode":"documents"}).raise_for_status().json()
                assert result["citations"] and "段落" in result["answer"] and "表格" in result["answer"]
                task_before=c.get("/task").json()
                split_documents(load_owned_document(owner,identity),10,2)
                assert c.get("/task").json()==task_before
                source=c.get("/documents/"+identity).raise_for_status().json()
                assert source["chunks"]==original["chunks"]
                assert other.get("/documents/"+identity).status_code==404
                assert c.post("/documents",files={"file":("bad.docx",b"broken")}).status_code==422
                assert len(c.get("/documents").json()["files"])==1
                assert c.post("/documents",files={"file":("fiction.docx",body)}).json()["id"]==identity
                c.delete("/documents/"+identity).raise_for_status()
                assert c.get("/documents/"+identity).status_code==404
                for i in range(MAX_FILES):
                    c.post("/documents",files={"file":(f"fiction{i}.txt",f"body{i}".encode())}).raise_for_status()
                assert c.post("/documents",files={"file":("excess.docx",docx_bytes())}).status_code==422
            print("PASS DOCX upload/list/source/summary/citations/delete, owner isolation, atomic failure/retry, quotas and unchanged canonical/task state")
        finally:
            general_agent.conn.close()


if __name__ == "__main__": run()
