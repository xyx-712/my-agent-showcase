"""Real embeddings/QA, fictional API uploads; only fresh temporary stores."""
import os,json,tempfile,time
from pathlib import Path
os.environ['MY_AGENT_RAG_ENABLED']='0'
os.environ.pop('MY_AGENT_CHROMA_DIR',None)
os.environ.pop('MY_AGENT_CHROMA_URL',None)
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup,close_test_chroma

def run():
 report={'threshold':.65,'rows':[]};start=time.perf_counter()
 with tempfile.TemporaryDirectory() as directory:
  app,agent,session,Service=setup(directory)
  from src.retrieval.service import enqueue
  from src.retrieval.qa import answer,lexical_evidence_terms
  from src.agent.model_provider import get_chat_model
  from src.server.documents import get_document
  service=Service();model=get_chat_model()
  try:
   with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
    client.post('/session',json={}).raise_for_status()
    def upload(name,text):
     response=client.post('/documents',files={'file':(name,text.encode())});response.raise_for_status();identity=response.json()['id']
     with session.app_db() as db:owner=db.execute('SELECT user_id FROM documents WHERE id=?',(identity,)).fetchone()[0]
     enqueue(owner,identity);assert service.run_once();return owner,identity
    fixture=json.loads(Path('tests/fixtures/rag_chinese.json').read_text(encoding='utf-8'));ids={}
    for d in fixture['documents']:owner,ids[d['id']]=upload(d['name'],d['text'])
    queries=[(q['question'],ids[q['expected']]) for q in fixture['queries']]+[('休年假要提前几日报批？',ids['leave']),('恢复数据库由谁负责？',ids['backup'])]
    queries += [(q,None) for q in ['火星大气中氩气的比例是多少？','量子纠缠的实验装置如何搭建？','巴黎铁塔有多高？','年假未休完可以折算多少元现金？']]
    for question,expected in queries:
     hits=service.search(owner,question,list(ids.values()),4)
     vector=[h for h in hits if 'vector' in h['retrieval_channels']];semantic=[h for h in vector if h['similarity']>=.65]
     old=semantic or [h for h in vector if lexical_evidence_terms(question,h['text'])]
     text,citations,audit=answer(owner,question,list(ids.values()),model,service)
     for citation in citations:
      original=get_document(owner,citation['file_id']);assert any(citation['text'] in chunk['text'] for chunk in original['chunks'])
     report['rows'].append({'question':question,'expected':expected,'vector':[{k:h[k] for k in ['document_id','similarity']} for h in vector],'lexical':[h['document_id'] for h in hits if 'lexical' in h['retrieval_channels']],'hybrid':audit,'old_policy_candidates':[h['document_id'] for h in old],'citations':[c['file_id'] for c in citations],'answer':text,'refused':not bool(citations)})
     print('ROW',len(report['rows']),bool(citations),flush=True)
    # Cross-document completion and original failure case.
    owner,a=upload('annual.txt','青禾公司员工年假额度为每年十五天。')
    _,b=upload('approval.txt','青禾公司年假申请需要提前三天向直属主管提交申请。')
    report['joint']={}
    for q in ['青禾公司年假额度与年假申请流程是什么？']:
     text,citations,audit=answer(owner,q,[a,b],model,service);report['joint']={'answer':text,'citations':[c['file_id'] for c in citations],'audit':audit,'both':{c['file_id'] for c in citations}=={a,b}}
    _,original=upload('original.txt','青禾公司每年提供十五天年假，申请须提前三天提交给直属主管审批。')
    text,citations,audit=answer(owner,'根据上传文件，每年年假有几天，找谁申请？',[original],model,service);report['original']={'answer':text,'citations':citations,'audit':audit}
    with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as other:
     other.post('/session',json={});report['foreign_file_status']=other.get('/documents/'+original).status_code
    response=client.delete('/documents/'+original);report['delete_status']=response.status_code
    try:service.search(owner,'年假申请？',[original]);report['deleted_search_blocked']=False
    except Exception:report['deleted_search_blocked']=True
  finally:
   agent.conn.close();close_test_chroma()
 report['seconds']=round(time.perf_counter()-start,3)
 Path('docs/rag-hybrid-real-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('REPORT SAVED',flush=True)
if __name__=='__main__':run()
