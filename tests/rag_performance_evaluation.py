"""Warm local component timings, not load-test latency guarantees."""
import json
import os
import tempfile
import time
from langchain_core.callbacks import BaseCallbackHandler
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup, close_test_chroma


class Timer(BaseCallbackHandler):
    def __init__(self):self.starts={};self.seconds=0
    def on_chat_model_start(self,serialized,messages,*,run_id,**kwargs):self.starts[run_id]=time.perf_counter()
    def on_llm_end(self,response,*,run_id,**kwargs):self.seconds+=time.perf_counter()-self.starts.pop(run_id)


def run():
    os.environ['MY_AGENT_RAG_ENABLED']='0'
    os.environ['MY_AGENT_EMBEDDING_MODEL']='embeddinggemma'
    os.environ.pop('MY_AGENT_CHROMA_URL',None);os.environ.pop('MY_AGENT_CHROMA_DIR',None)
    with tempfile.TemporaryDirectory() as directory:
        before=time.perf_counter();app,agent,session,Service=setup(directory)
        report={'import_and_graph_setup_seconds':time.perf_counter()-before}
        from src.retrieval.service import enqueue,statuses
        from src.retrieval.embeddings import settings,OllamaVectors
        from src.retrieval.store import VectorStore
        from src.retrieval.qa import answer
        timer=Timer();agent.llm=agent.llm.model_copy(update={'callbacks':[timer]})
        try:
            before=time.perf_counter()
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
                report['lifespan_start_seconds']=time.perf_counter()-before
                client.post('/session',json={}).raise_for_status()
                identity=client.post('/documents',files={'file':('policy.txt','员工每年享有十五天带薪年假，休假须提前三天向直属主管提交申请。'.encode())}).raise_for_status().json()['id']
                with session.app_db() as db:owner=db.execute('SELECT user_id FROM documents WHERE id=?',(identity,)).fetchone()[0]
                service=Service();before=time.perf_counter();service.run_once()
                report['initial_index_seconds']=time.perf_counter()-before
                backend=OllamaVectors(settings());revision=backend.identity()
                before=time.perf_counter();vector=backend.embed_query('员工年假有几天，找谁申请？')
                report['embedding_query_rpc_seconds']=time.perf_counter()-before
                row=statuses(owner)[identity];store=VectorStore(owner,settings().key,revision,backend)
                before=time.perf_counter();assert store.search(vector,owner,identity,row['generation'],4)
                report['embedded_vector_search_seconds']=time.perf_counter()-before
                before=time.perf_counter();assert service.search(owner,'员工年假有几天，找谁申请？',[identity])
                report['authorized_retrieval_including_embedding_seconds']=time.perf_counter()-before
                timer.seconds=0;before=time.perf_counter()
                text,citations,_=answer(owner,'员工年假有几天，找谁申请？',[identity],agent.llm,service)
                assert citations,text
                report['rag_total_seconds']=time.perf_counter()-before
                report['rag_chat_model_rpc_seconds']=timer.seconds
                report['rag_other_including_embedding_seconds']=report['rag_total_seconds']-timer.seconds
                timer.seconds=0;before=time.perf_counter()
                client.post('/chat',json={'message':'你好，请用一句话介绍你自己。','mode':'chat'}).raise_for_status()
                report['ordinary_chat_total_seconds']=time.perf_counter()-before
                report['ordinary_chat_model_rpc_seconds']=timer.seconds
                report['ordinary_chat_other_seconds']=report['ordinary_chat_total_seconds']-timer.seconds
                enqueue(owner,identity,True);before=time.perf_counter();service.run_once()
                assert statuses(owner)[identity]['status']=='READY'
                report['rebuild_seconds']=time.perf_counter()-before
            print(json.dumps(report,indent=2),flush=True)
        finally:
            agent.conn.close();close_test_chroma()


if __name__=='__main__':run()
