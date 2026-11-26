"""Real Chroma with substitute/real embeddings; all source/vector data is temporary."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from langchain_core.embeddings import Embeddings
from fastapi.testclient import TestClient


class FakeVectors(Embeddings):
    revision = "fake-revision-1"
    unavailable = False
    fail_after = None
    batches = 0

    def __init__(self, config):
        self.dimension = 4

    def identity(self):
        if self.unavailable:
            raise ConnectionError("injected embedding outage")
        return self.revision

    def vector(self, text):
        groups = [("年假","休假","假期","主管"),("退货","退款","运费","收货"),("备份","恢复","数据库"),("密码","登录","审计")]
        values=[.01+sum(word in text for word in group) for group in groups]
        norm=math.sqrt(sum(v*v for v in values))
        return [v/norm for v in values]

    def embed_documents(self, texts):
        type(self).batches += 1
        if self.fail_after is not None and self.batches > self.fail_after:
            raise ConnectionError("injected mid-index failure")
        return [self.vector(t) for t in texts]

    def embed_query(self, text):
        if self.unavailable:
            raise ConnectionError("injected embedding outage")
        return self.vector(text)


def setup(directory):
    from src import config
    for name in ("APP_DB","MEMORY_DB","CHECKPOINT_DB"):
        setattr(config,name,Path(directory)/(name+".db"))
    from src.server import history
    history.HISTORY_FILE=Path(directory)/"history.json"
    from src.server.api import app,general_agent
    from src.server import session
    assert session.APP_DB.resolve().is_relative_to(Path(directory).resolve())
    from src.retrieval.service import IndexService
    return app,general_agent,session,IndexService


def close_test_chroma():
    import gc
    gc.collect()
    # Release only this isolated test process's Chroma systems before Windows temp cleanup.
    from chromadb.api.shared_system_client import SharedSystemClient
    for system in list(SharedSystemClient._identifier_to_system.values()):
        system.stop()
    SharedSystemClient.clear_system_cache()
    gc.collect()
    time.sleep(.2)


def restart_phase(directory, phase):
    app,agent,session,Service=setup(directory)
    from src.retrieval.service import enqueue,statuses
    service=Service(backend_factory=FakeVectors)
    try:
        with TestClient(app) as client:
            state_file=Path(directory)/"phase.json"
            if phase=="build":
                from src.server.documents import store_document
                owner="restart-fictional-user"
                identity=store_document(owner,"restart.txt","年假十五天，向主管申请。".encode())
                enqueue(owner,identity)
                service.run_once()
                assert statuses(owner)[identity]["status"]=="READY"
                state_file.write_text(json.dumps({"owner":owner,"id":identity}),encoding="utf-8")
            else:
                saved=json.loads(state_file.read_text(encoding="utf-8"))
                owner,identity=saved['owner'],saved['id']
                if phase=="read":
                    assert service.search(owner,"休假多久？",[identity])
                    assert FakeVectors.batches==0, "READY index must persist without rebuilding"
                    enqueue(owner,identity,True)
                    with session.app_db() as db:
                        db.execute("UPDATE rag_indexes SET status='INDEXING',worker_token='dead-process',lease_until=0")
                elif phase=="recover":
                    assert service.run_once()
                    assert service.search(owner,"休假多久？",[identity])
                    assert statuses(owner)[identity]["status"]=="READY"
        print("PASS restart phase",phase)
    finally:
        agent.conn.close()
        close_test_chroma()


def run(real=False):
    os.environ["MY_AGENT_RAG_ENABLED"]="0"
    os.environ["MY_AGENT_EMBEDDING_MODEL"]="embeddinggemma" if real else "fake-embeddings"
    os.environ["MY_AGENT_EMBEDDING_URL"]="http://127.0.0.1:11434"
    os.environ.pop("MY_AGENT_CHROMA_URL",None)
    os.environ.pop("MY_AGENT_CHROMA_DIR",None)
    started=time.perf_counter()
    fixture=json.loads((Path(__file__).parent/"fixtures/rag_chinese.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,Service=setup(directory)
        from src.retrieval.service import enqueue,statuses,remove_document
        from src.retrieval.embeddings import OllamaVectors,settings
        service=Service(backend_factory=OllamaVectors if real else FakeVectors)
        if not real:
            from tests.planner_evaluation import PlanningModel
            agent.llm=PlanningModel()
        try:
            with TestClient(app,headers={"Origin":"http://127.0.0.1:5173"}) as client:
                from src.server.documents import store_document
                owner="fictional-owner-a"
                other="fictional-owner-b"
                ids={}
                for document in fixture['documents']:
                    identity=store_document(owner,document['name'],document['text'].encode())
                    ids[document['id']]=identity
                    first=enqueue(owner,identity)
                    duplicate=enqueue(owner,identity)
                    assert first['generation']==duplicate['generation']
                    assert service.run_once()
                    assert statuses(owner)[identity]['status']=='READY', statuses(owner)
                before=FakeVectors.batches
                generation=enqueue(owner,ids['leave'])['generation']
                assert not service.run_once()
                assert before==FakeVectors.batches
                correct=0
                outcomes=[]
                for query in fixture['queries']:
                    hits=service.search(owner,query['question'],k=3)
                    matched=bool(hits) and hits[0]['document_id']==ids[query['expected']]
                    correct+=matched
                    outcomes.append({**query,'top1_correct':matched,'distance':hits[0]['distance'] if hits else None})
                print(json.dumps({'model':settings().model,'dimensions':statuses(owner)[ids['leave']]['dimension'],
                                  'recall_at_1':f"{correct}/{len(outcomes)}",'results':outcomes},ensure_ascii=False),flush=True)
                assert correct>=6
                hidden=store_document(other,"private.txt","退款只给另一个账号，秘密测试。".encode())
                enqueue(other,hidden); service.run_once()
                assert all(h['document_id']!=hidden for h in service.search(owner,"退款",k=20))
                try:
                    service.search(owner,"退款",[hidden])
                    raise AssertionError("foreign document accepted")
                except Exception as error:
                    assert getattr(error,'status_code',None)==404
                limited=service.search(owner,"年假",[ids['leave']],1)
                assert len(limited)==1 and limited[0]['source']['name']=='leave.txt'
                if real:
                    if '--qa' in sys.argv:
                        from src.retrieval.qa import answer
                        text, citations, audit = answer(owner, '员工年假有几天，找谁申请？', list(ids.values()), agent.llm, service)
                        assert citations, (text, audit)
                        assert '主管' in text, text
                        print('PASS real RAG answer', text, json.dumps(audit, ensure_ascii=False), flush=True)
                        text, citations, audit = answer(owner, '火星大气中氩气的比例是多少？', list(ids.values()), agent.llm, service)
                        assert not citations, (text, audit)
                        print('PASS real unrelated question refusal', text, flush=True)
                    print('PASS real Chinese embedding + persistent Chroma, multi-document scopes, isolation',round(time.perf_counter()-started,3),'seconds')
                    return
                from src.retrieval.store import VectorStore
                raced=store_document(owner,"raced.txt","年假并发代次测试。".encode())
                old_job=enqueue(owner,raced)
                def replacing_store(*args):
                    store=VectorStore(*args)
                    original=store.upsert
                    def replace_generation(*items):
                        original(*items)
                        enqueue(owner,raced,True)
                    store.upsert=replace_generation
                    return store
                Service(backend_factory=FakeVectors,store_factory=replacing_store).run_once()
                assert statuses(owner)[raced]['status']=='PENDING'
                assert enqueue(owner,raced)['generation']!=old_job['generation']
                assert not service.search(owner,"年假",[raced])
                service.run_once()
                assert statuses(owner)[raced]['status']=='READY'
                remove_document(owner,raced)
                service.cleanup()
                old=enqueue(owner,ids['leave'])
                FakeVectors.revision="fake-revision-2"
                assert not service.search(owner,"年假",[ids['leave']])
                assert statuses(owner)[ids['leave']]['status']=='PENDING'
                service.run_once()
                assert enqueue(owner,ids['leave'])['generation']!=generation
                assert service.search(owner,"年假",[ids['leave']])
                with patch.dict(os.environ,{"MY_AGENT_EMBEDDING_MODEL":"changed-model"}):
                    assert statuses(owner)[ids['leave']]['status']=='PENDING'
                    assert not service.search(owner,"年假",[ids['leave']])
                # Return the configured model and explicitly rebuild after the temporary change.
                enqueue(owner,ids['leave'],True); service.run_once()
                FakeVectors.unavailable=True
                failed_id=store_document(owner,"offline.txt","年假测试".encode())
                enqueue(owner,failed_id); service.run_once()
                assert statuses(owner)[failed_id]['status']=='FAILED'
                assert statuses(owner)[failed_id]['failure_reason']
                FakeVectors.unavailable=False
                enqueue(owner,failed_id,True); service.run_once()
                assert statuses(owner)[failed_id]['status']=='READY'
                def broken_store(*args): raise RuntimeError('injected Chroma failure')
                enqueue(owner,failed_id,True)
                Service(backend_factory=FakeVectors,store_factory=broken_store).run_once()
                assert statuses(owner)[failed_id]['status']=='FAILED'
                enqueue(owner,failed_id,True); service.run_once()
                long_id=store_document(owner,"long.txt",("年假政策研究正文。"*40+"\n").encode()*100)
                enqueue(owner,long_id)
                FakeVectors.batches=0; FakeVectors.fail_after=1
                service.run_once()
                assert statuses(owner)[long_id]['status']=='FAILED'
                assert not service.search(owner,"年假",[long_id])
                FakeVectors.fail_after=None
                enqueue(owner,long_id,True); service.run_once()
                assert statuses(owner)[long_id]['status']=='READY'
                snapshot=enqueue(owner,failed_id)
                remove_document(owner,failed_id)
                assert all(h['document_id']!=failed_id for h in service.search(owner,"年假"))
                service.cleanup()
                from src.retrieval.store import VectorStore
                store=VectorStore(owner,snapshot['settings_key'],snapshot['model_revision'],None)
                assert store.count(owner,failed_id,snapshot['generation'])==0
                # API identity is cookie-derived; client user/collection/filter injection is forbidden.
                client.post('/session',json={}).raise_for_status()
                uploaded=client.post('/documents',files={'file':('own.txt','年假十五天。'.encode())}).raise_for_status().json()
                assert client.post('/documents/'+uploaded['id']+'/reindex',json={}).status_code==200
                assert client.get('/documents').json()['files'][0]['index']['status']=='PENDING'
                assert client.post('/documents/'+hidden+'/reindex',json={}).status_code==404
                assert client.post('/retrieval/search',json={'query':'年假','user_id':other}).status_code==422
                assert client.post('/retrieval/search',json={'query':'年假','collection':'bad'}).status_code==422
                with patch('src.retrieval.service.IndexService',return_value=service):
                    assert client.post('/retrieval/search',json={'query':'退款','document_ids':[hidden]}).status_code==404
                    assert client.post('/retrieval/search',json={'query':'年假','document_ids':[]}).json()['hits']==[]
            FakeVectors.unavailable=True
            with patch.dict(os.environ, {'MY_AGENT_RAG_ENABLED':'1'}), patch('src.retrieval.service.IndexService',return_value=service):
                with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as offline_client:
                    offline_client.post('/session',json={}).raise_for_status()
                    result=offline_client.post('/chat',json={'message':'1+4=?','mode':'chat'}).raise_for_status().json()
                    assert '计算结果：5' in result['answer']
                    result=offline_client.post('/chat',json={'message':'普通闲聊','mode':'chat'}).raise_for_status().json()
                    assert result['answer']=='普通聊天回复'
            FakeVectors.unavailable=False
            print('PASS idempotency, failure/retry, model/digest invalidation, partial failure, physical delete and API scopes')
        finally:
            agent.conn.close()
            close_test_chroma()
    # Actual sequential process exits/restarts, never concurrent embedded writers.
    with tempfile.TemporaryDirectory() as directory:
        for phase in ('build','read','recover'):
            result=subprocess.run([sys.executable,'-X','utf8','-m','tests.vector_index_evaluation','--phase',phase,directory],capture_output=True,text=True,encoding='utf-8',timeout=90)
            assert result.returncode==0,result.stdout+result.stderr
            print(result.stdout.strip())


def automatic_real():
    os.environ['MY_AGENT_RAG_ENABLED']='1'
    os.environ['MY_AGENT_EMBEDDING_MODEL']='embeddinggemma'
    os.environ['MY_AGENT_EMBEDDING_URL']='http://127.0.0.1:11434'
    os.environ.pop('MY_AGENT_CHROMA_DIR',None)
    os.environ.pop('MY_AGENT_CHROMA_URL',None)
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,Service=setup(directory)
        started=time.perf_counter()
        try:
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
                client.post('/session',json={}).raise_for_status()
                identity=client.post('/documents',files={'file':('automatic.txt','员工年假十五天，向主管申请。'.encode())}).raise_for_status().json()['id']
                def wait_ready():
                    for _ in range(120):
                        files=client.get('/documents').raise_for_status().json()['files']
                        current=next(f for f in files if f['id']==identity)['index']
                        if current['status']=='READY': return current
                        assert current['status']!='FAILED',current
                        time.sleep(.5)
                    raise AssertionError('background index exceeded 60 seconds')
                first=wait_ready()
                result=client.post('/retrieval/search',json={'query':'休假要找谁申请？','document_ids':[identity],'top_k':1}).raise_for_status().json()
                assert len(result['hits'])==1 and result['hits'][0]['document_id']==identity
                client.post('/documents/'+identity+'/reindex',json={}).raise_for_status()
                assert wait_ready()['generation']!=first['generation']
                result=client.post('/chat',json={'message':'1+4=?','mode':'chat'}).raise_for_status().json()
                assert '计算结果：5' in result['answer']
                client.delete('/documents/'+identity).raise_for_status()
                assert client.get('/documents/'+identity).status_code==404
            print('PASS automatic background real index -> READY, API vector search, reindex, ordinary tool and delete',round(time.perf_counter()-started,3),'seconds')
        finally:
            agent.conn.close()
            close_test_chroma()


if __name__=='__main__':
    if '--auto-real' in sys.argv:
        automatic_real()
    elif '--phase' in sys.argv:
        os.environ['MY_AGENT_EMBEDDING_MODEL']='fake-embeddings'
        restart_phase(sys.argv[-1],sys.argv[sys.argv.index('--phase')+1])
    else:
        run('--real' in sys.argv)
