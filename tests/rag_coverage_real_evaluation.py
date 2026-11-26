"""Real API + Ollama + Chroma coverage regression; fresh stores only."""
import os,sys,json,time,tempfile,re
from pathlib import Path
from unittest.mock import patch

def run():
 root=Path.cwd();parent=root/'.rag-validation-runs';parent.mkdir(exist_ok=True);run=Path(tempfile.mkdtemp(prefix='coverage-',dir=parent))
 os.environ.update(MY_AGENT_MODE='demo',MY_AGENT_DEMO_DATA_DIR=str(run/'db'),MY_AGENT_CHROMA_DIR=str(run/'chroma'),MY_AGENT_PUBLIC_ORIGIN='https://testserver',MY_AGENT_RAG_ENABLED='0',MY_AGENT_MODEL='qwen2.5:7b',MY_AGENT_OLLAMA_URL='http://127.0.0.1:11434',MY_AGENT_EMBEDDING_MODEL='embeddinggemma:latest',MY_AGENT_EMBEDDING_URL='http://127.0.0.1:11434',MY_AGENT_RAG_MIN_SIMILARITY='0.65')
 for name in ['MY_AGENT_CHROMA_URL','MY_AGENT_OLLAMA_API_KEY']:os.environ.pop(name,None)
 def guard(event,args):
  if event=='sqlite3.connect' and not Path(args[0]).resolve().is_relative_to(run/'db'):raise RuntimeError('Database outside fresh test run')
 sys.addaudithook(guard)
 from fastapi.testclient import TestClient
 from src.server.api import app,general_agent
 from src.server import session
 from src.retrieval.service import IndexService,enqueue,statuses
 from src.agent import execution
 from tests.vector_index_evaluation import close_test_chroma
 service=IndexService();report={'run':str(run),'cases':[],'threshold':.65,'model':'qwen2.5:7b','embedding':'embeddinggemma:latest'};original=execution.invoke_model;started=time.perf_counter()
 try:
  with TestClient(app,base_url='https://testserver',headers={'Origin':'https://testserver'}) as client:
   # Startup background thread was disabled; now enable the real RAG request route.
   # IndexService builds only our fresh documents synchronously below.
   os.environ['MY_AGENT_RAG_ENABLED']='1'
   client.post('/session',json={}).raise_for_status();ids={}
   fixture=json.loads(Path('tests/fixtures/rag_chinese.json').read_text(encoding='utf-8'));texts={d['id']:(d['name'],d['text']) for d in fixture['documents']};texts['leave']=('leave.txt','青禾公司每年提供十五天年假，申请须提前三天提交给直属主管审批。')
   for key,(name,text) in texts.items():
    response=client.post('/documents',files={'file':(name,text.encode())});response.raise_for_status();ids[key]=response.json()['id']
    with session.app_db() as db:owner=db.execute('select user_id from documents where id=?',(ids[key],)).fetchone()[0]
    enqueue(owner,ids[key]);assert service.run_once();assert statuses(owner)[ids[key]]['status']=='READY'
   def ask(q,expected=None,required=None,label=''):
    record={'question':q,'label':label,'calls':[],'expected_files':[ids[k] for k in expected] if expected else []}
    def capture(model,messages):
     response=original(model,messages);record['calls'].append({'messages':[m.model_dump(mode='json') for m in messages],'raw':response.content});return response
    with patch.object(execution,'invoke_model',capture):response=client.post('/chat',json={'message':q,'mode':'documents'})
    record['http_status']=response.status_code;record['response']=response.json()
    if response.status_code==200:
     value=record['response'];citations=value.get('citations',[]);record['literal_quotes_ok']=True
     for c in citations:
      doc=client.get('/documents/'+c['file_id']).raise_for_status().json()
      if not any(c['text'] in chunk['text'] for chunk in doc['chunks']):record['literal_quotes_ok']=False
     # Check prose independently of quotes/labels.
     prose='\n'.join(line for line in value.get('answer','').splitlines() if not line.startswith('依据：'))
     record['required_prose_ok']=all(term in prose for term in (required or []))
     if label in {'recovery','joint'}:
      record['required_prose_ok']=record['required_prose_ok'] and bool(re.search(r'管理员.{0,10}(?:执行|恢复)',prose)) and bool(re.search(r'(?:核对|检查).{0,12}完整性',prose))
     files={c['file_id'] for c in citations};record['files_ok']=set(record['expected_files']).issubset(files) if expected else not files
     record['rag_route_verified']=any('question_parts' in json.loads(m['content']) for call in record['calls'] for m in call['messages'] if m['type']=='human' and isinstance(m['content'],str) and m['content'].startswith('{')) if citations else True
     record['passed']=record['literal_quotes_ok'] and record['required_prose_ok'] and record['files_ok'] and record['rag_route_verified']
    else:record['passed']=False
    report['cases'].append(record);print('CASE',label,record['passed'],flush=True);return record
   ask('谁有权恢复数据，需要检查什么？',['backup'],['管理员','完整性'],'recovery')
   ask('请根据上传文件回答：年假有几天、由谁审批，数据库由谁恢复并核对什么？',['leave','backup'],['主管','管理员','完整性'],'joint')
   ask('设置登录密码有什么要求？',['security'],['十二','字母','数字'],'password')
   ask('发现有人异常登录账号应该如何处理？',['security'],['撤销','会话'],'abnormal')
   before=service.search(owner,'根据上传文件，每年年假有几天，找谁申请？',[ids['leave']],4);report['original_similarity']=before[0]['similarity']
   ask('根据上传文件，每年年假有几天，找谁申请？',['leave'],['主管'],'original')
   ask('年假未休完可以折算多少元现金？',label='missing')
   ask('火星大气中氩气的比例是多少？请只根据上传文件回答。',label='unrelated')
   for n,item in enumerate(fixture['queries']):ask(item['question'],[item['expected']],label='original10-'+str(n+1))
   ask('休年假要提前几日报批？',['leave'],label='original10-9');ask('恢复数据库由谁负责？',['backup'],label='original10-10')
   other=TestClient(app,base_url='https://testserver',headers={'Origin':'https://testserver'});other.post('/session',json={}).raise_for_status()
   report['foreign_get_status']=other.get('/documents/'+ids['backup']).status_code
   report['foreign_search_status']=other.post('/retrieval/search',json={'query':'谁恢复数据','document_ids':[ids['backup']],'top_k':4}).status_code;other.close()
   report['delete_status']=client.delete('/documents/'+ids['leave']).status_code
   deleted=ask('根据上传文件，每年年假有几天，找谁申请？',label='deleted')
   report['deleted_citations_absent']=not deleted['response'].get('citations')
   with session.app_db() as db:report['rag_task_audits']=[json.loads(row[0]) for row in db.execute('select state from agent_tasks')]
 finally:
  general_agent.conn.close();close_test_chroma()
 report['seconds']=round(time.perf_counter()-started,3);report['passed']=sum(x['passed'] for x in report['cases']);report['total']=len(report['cases'])
 (run/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');Path('docs/rag-coverage-real-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('FINISHED',report['passed'],report['total'],report['foreign_get_status'],report['foreign_search_status'],report['seconds'],flush=True)
if __name__=='__main__':run()
