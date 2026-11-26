"""Real refused local connections and injected SQLite error, temporary business data."""
import os
import sqlite3
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from langchain_ollama import ChatOllama
from tests.vector_index_evaluation import setup,FakeVectors,close_test_chroma


def run():
    os.environ['MY_AGENT_RAG_ENABLED']='0'
    os.environ['MY_AGENT_EMBEDDING_MODEL']='embeddinggemma'
    os.environ.pop('MY_AGENT_CHROMA_URL',None);os.environ.pop('MY_AGENT_CHROMA_DIR',None)
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,Service=setup(directory)
        from src.retrieval.service import enqueue,statuses
        try:
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as c:
                c.post('/session',json={}).raise_for_status()
                identity=c.post('/documents',files={'file':('fault.txt','年假十五天。'.encode())}).raise_for_status().json()['id']
                with session.app_db() as db:owner=db.execute('SELECT user_id FROM documents WHERE id=?',(identity,)).fetchone()[0]
                with patch.dict(os.environ,{'MY_AGENT_EMBEDDING_URL':'http://127.0.0.1:1'}):
                    enqueue(owner,identity,True);Service().run_once()
                    assert statuses(owner)[identity]['status']=='FAILED'
                with patch.dict(os.environ,{'MY_AGENT_EMBEDDING_MODEL':'fictional-model-not-installed-stage4'}):
                    enqueue(owner,identity,True);Service().run_once()
                    assert statuses(owner)[identity]['status']=='FAILED'
                enqueue(owner,identity,True)
                substitute=Service(backend_factory=FakeVectors)
                substitute.run_once()
                assert statuses(owner)[identity]['status']=='READY'
                with patch('src.retrieval.service.IndexService',return_value=substitute), \
                     patch('src.retrieval.service.database',side_effect=sqlite3.OperationalError('injected SQLite index-state access failure')):
                    assert c.post('/retrieval/search',json={'query':'年假','document_ids':[identity]}).status_code==503
                assert statuses(owner)[identity]['status']=='READY'
                from tests.planner_evaluation import PlanningModel
                agent.llm=PlanningModel()
                with patch.dict(os.environ,{'MY_AGENT_CHROMA_URL':'http://127.0.0.1:1'}):
                    result=c.post('/chat',json={'message':'你好','mode':'chat'}).raise_for_status().json()
                    assert result['answer']=='普通聊天回复'
                agent.llm=ChatOllama(model='qwen2.5:7b',base_url='http://127.0.0.1:1',client_kwargs={'timeout':1})
                result=c.post('/chat',json={'message':'你好','mode':'chat'}).raise_for_status().json()
                assert '暂不可用' in result['answer'],result
                assert '5' in c.post('/chat',json={'message':'1+4=?','mode':'chat'}).raise_for_status().json()['answer']
            print('PASS Embedding offline/missing-model -> FAILED -> retry; SQLite index access ->503 unchanged state; Ollama offline -> bounded planning error, arithmetic remains usable')
        finally:
            agent.conn.close();close_test_chroma()


if __name__=='__main__':run()
