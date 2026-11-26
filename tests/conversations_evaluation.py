"""Authenticated multi-chat integration, isolated databases and fictional files."""
import json
import os
from pathlib import Path
import tempfile
import time
import subprocess
import sys
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup,FakeVectors,close_test_chroma
from tests.history_summary_evaluation import Model


def run():
    os.environ.update(MY_AGENT_RAG_ENABLED='0',MY_AGENT_EMBEDDING_MODEL='fake-embeddings',MY_AGENT_CONTEXT_TURNS='2',MY_AGENT_SUMMARY_MIN_TURNS='2',MY_AGENT_SUMMARY_BATCH_TURNS='2')
    os.environ.pop('MY_AGENT_CHROMA_URL',None);os.environ.pop('MY_AGENT_CHROMA_DIR',None)
    timings={};started=time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,Service=setup(directory);model=Model();agent.llm=model
        from src.server.conversations import bind,thread
        from src.server.history import save_history
        from src.agent.history_summary import load
        from src.server.backup import backup,restore
        from src.memory.store import memory_store
        headers={'Origin':'http://127.0.0.1:5173'}
        try:
            startup=time.perf_counter()
            with TestClient(app,headers=headers) as a:
                timings['lifespan_start_ms']=round((time.perf_counter()-startup)*1000,2)
                credentials={'username':'chats_fictional','password':'fictional-password-123'}
                a.post('/auth/register',json=credentials).raise_for_status()
                other=TestClient(app,headers=headers);other.post('/session',json={}).raise_for_status()
                default=a.get('/conversations').json()['sessions'][0]
                assert default['is_default']
                create_started=time.perf_counter()
                one=a.post('/conversations',json={'name':'项目甲'}).raise_for_status().json()['id']
                two=a.post('/conversations',json={'name':'项目乙'}).raise_for_status().json()['id']
                timings['two_creates_ms']=round((time.perf_counter()-create_started)*1000,2)
                def choose(identity):a.headers['X-Chat-Session']=identity
                def chat(text,**extra):return a.post('/chat',json={'message':text,'mode':'chat',**extra}).raise_for_status().json()
                choose(one);chat('我叫李四')
                chat('甲会话独有口令：青禾')
                with session.app_db() as db:owner=db.execute('SELECT user_id FROM accounts WHERE username=?',('chats_fictional',)).fetchone()[0]
                choose(two);read_started=time.perf_counter()
                assert a.get('/history').json()['messages']==[]
                timings['empty_session_history_ms']=round((time.perf_counter()-read_started)*1000,2)
                result=chat('我叫什么')
                assert any(item['key']=='name' and item['value']=='李四' for item in result['memory'])
                assert 'name: 李四' in model.answers[-1][0].content
                assert not any('甲会话独有口令' in m.content for m in model.answers[-1]),(result,[(m.type,m.content) for m in model.answers[-1]])
                assert other.get('/history',headers={'X-Chat-Session':one}).status_code==404
                assert other.delete('/conversations/'+one,headers={'Content-Type':'application/json'}).status_code==404
                assert other.post('/conversations/'+one+'/restore',json={}).status_code==404
                assert a.post('/conversations',json={'name':'伪造','user_id':owner}).status_code==422
                assert a.post('/chat',json={'message':'你好','session_id':one}).status_code==409
                a.headers.pop('X-Chat-Session');assert a.post('/chat',json={'message':'body session','session_id':two,'mode':'chat'}).status_code==200
                assert a.get('/history').json()['messages']==[] # legacy default remains separate
                # Seed short recent turns and older project facts in both sessions.
                for identity,project in ((one,'青禾甲'),(two,'白榆乙')):
                    with bind(owner,identity):
                        for text in (f'项目{project}需要离线',f'项目{project}禁止删除文件','普通问候','最近闲聊'):
                            save_history(owner,'user',text);save_history(owner,'assistant','已收到')
                    choose(identity);chat('项目背景是什么？')
                    with bind(owner,identity):first_digest=load(owner)
                    if not first_digest:chat('继续项目背景') # one bounded extra batch after initial non-project turns
                    with bind(owner,identity):
                        digest=load(owner);assert digest
                        assert project in json.dumps(digest,ensure_ascii=False)
                        assert agent.graph.get_state({'configurable':{'thread_id':thread(owner)}}).values['history_summary']
                choose(one)
                document=a.post('/documents',files={'file':('leave.txt','员工年假十五天，提前三天向主管申请。'.encode())}).raise_for_status().json()['id']
                task=a.post('/tasks/new',json={'name':'甲任务'}).raise_for_status().json()['id']
                service=Service(backend_factory=FakeVectors)
                while service.run_once():pass
                with bind(owner,one):
                    search_started=time.perf_counter();assert service.search(owner,'员工年假有几天？',[document])
                    timings['substitute_embedding_vector_search_ms']=round((time.perf_counter()-search_started)*1000,2)
                with patch('src.retrieval.service.enabled',return_value=True),patch('src.retrieval.qa.IndexService',return_value=service):
                    rag_started=time.perf_counter()
                    rag=a.post('/chat',json={'message':'员工年假有几天？','mode':'documents'}).raise_for_status().json()
                    assert rag['citations'] and rag['citations'][0]['file_id']==document
                    timings['substitute_model_rag_request_ms']=round((time.perf_counter()-rag_started)*1000,2)
                choose(two)
                assert a.get('/documents').json()['files']==[] and a.get('/tasks').json()['tasks']==[]
                assert a.get('/documents/'+document).status_code==404
                assert a.post('/tasks/select',json={'id':task}).status_code==404
                assert a.post('/retrieval/search',json={'query':'年假','document_ids':[document]}).status_code==404
                with patch('src.retrieval.service.enabled',return_value=True),patch('src.retrieval.qa.IndexService',return_value=service):
                    hidden=a.post('/chat',json={'message':'根据上传文件，员工年假有几天？','mode':'auto'}).raise_for_status().json()
                    assert not hidden['citations'],hidden # prove scope survives the LangGraph thread boundary
                duplicate=a.post('/documents',files={'file':('leave.txt','员工年假十五天，提前三天向主管申请。'.encode())}).raise_for_status().json()['id']
                assert duplicate==document
                a.delete('/documents/'+duplicate).raise_for_status()
                choose(one);assert a.get('/documents/'+document).status_code==200
                # Same request IDs are independently namespaced, never replay A into B.
                first=chat('1+4=?',request_id='same-id-123')
                choose(two);second=chat('2+6=?',request_id='same-id-123')
                assert '5' in first['answer'] and '8' in second['answer']
                choose(one);before=a.get('/history').json()
                a.delete('/conversations/'+one,headers={'Content-Type':'application/json'}).raise_for_status()
                assert a.get('/history').status_code==404 and a.get('/documents').status_code==404
                choose(two);assert a.get('/history').status_code==200
                a.post('/conversations/'+one+'/restore',json={}).raise_for_status()
                choose(one);assert a.get('/history').json()==before
                assert a.get('/documents/'+document).status_code==200
                second_browser=TestClient(app,headers=headers)
                second_browser.post('/auth/login',json=credentials).raise_for_status()
                assert second_browser.get('/history',headers={'X-Chat-Session':one}).json()==before
                # Old default retains original checkpoint key.
                assert agent.graph.get_state({'configurable':{'thread_id':owner}}).values=={}
                a.headers.pop('X-Chat-Session');chat('默认会话的消息')
                assert agent.graph.get_state({'configurable':{'thread_id':owner}}).values
                backup_started=time.perf_counter();snapshot=Path(directory)/'snapshot';backup(snapshot)
                timings['backup_ms']=round((time.perf_counter()-backup_started)*1000,2)
            agent.conn.close();restore(snapshot,True)
            with TestClient(app,headers=headers) as restored:
                restored.post('/auth/login',json=credentials).raise_for_status()
                assert restored.get('/history',headers={'X-Chat-Session':one}).json()==before
                assert restored.get('/documents/'+document,headers={'X-Chat-Session':one}).status_code==200
                assert memory_store.get(owner,'name')=='李四'
                assert len(restored.get('/conversations').json()['sessions'])==3
            timings['suite_seconds']=round(time.perf_counter()-started,3)
            print('PASS conversations create/switch/soft delete/restore, scoped history/summary/checkpoint/files/tasks/RAG/idempotency, shared memory, account isolation, second browser and backup restore')
            print(json.dumps(timings,ensure_ascii=False))
        finally:agent.conn.close();close_test_chroma()


def restart_phase(directory,phase):
    os.environ.update(MY_AGENT_RAG_ENABLED='0')
    app,agent,session,_=setup(directory);agent.llm=Model()
    credentials={'username':'restart_chats','password':'fictional-password-123'}
    try:
        with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
            if phase=='build':
                client.post('/auth/register',json=credentials).raise_for_status()
                one=client.post('/conversations',json={'name':'待恢复甲'}).json()['id']
                two=client.post('/conversations',json={'name':'独立乙'}).json()['id']
                client.headers['X-Chat-Session']=one
                client.post('/chat',json={'message':'我叫李四','mode':'chat'}).raise_for_status()
                for name in ('plan.txt','change.md'):
                    client.post('/documents',files={'file':(name,(Path(__file__).parent/'fixtures'/name).read_bytes())}).raise_for_status()
                os.environ['MY_AGENT_FAIL_CALCULATOR_ONCE']='1'
                failed=client.post('/chat',json={'message':'计算剩余工期','mode':'documents'}).raise_for_status().json()
                assert '临时故障' in failed['answer'],failed
                os.environ.pop('MY_AGENT_FAIL_CALCULATOR_ONCE',None)
                client.headers['X-Chat-Session']=two
                client.post('/chat',json={'message':'你好','mode':'chat'}).raise_for_status()
                Path(directory,'chat-phase.json').write_text(json.dumps({'one':one,'two':two,'task':failed['task']['id']}))
            else:
                saved=json.loads(Path(directory,'chat-phase.json').read_text())
                client.post('/auth/login',json=credentials).raise_for_status()
                client.headers['X-Chat-Session']=saved['two']
                assert client.get('/tasks').json()['tasks']==[] and client.get('/documents').json()['files']==[]
                client.headers['X-Chat-Session']=saved['one']
                result=client.post('/chat',json={'message':'继续任务','mode':'documents','task_id':saved['task']}).raise_for_status().json()
                assert result['task']['id']==saved['task'] and result['tool_calls']==['calculator']
                assert '剩余 15' in result['answer'] and result['citations']
                assert agent.graph.get_state({'configurable':{'thread_id':'chat:'+saved['one']}}).values['chat_session_id']==saved['one']
                assert agent.graph.get_state({'configurable':{'thread_id':'chat:'+saved['two']}}).values['chat_session_id']==saved['two']
            print('PASS fresh-process conversation/task/checkpoint',phase)
    finally:agent.conn.close()


def restart():
    with tempfile.TemporaryDirectory() as directory:
        for phase in ('build','resume'):
            subprocess.run([sys.executable,'-X','utf8','-m','tests.conversations_evaluation','--phase',directory,phase],check=True,timeout=45)


def real():
    os.environ.update(MY_AGENT_RAG_ENABLED='0',MY_AGENT_MODEL='qwen2.5:7b',MY_AGENT_OLLAMA_URL='http://127.0.0.1:11434')
    started=time.perf_counter();timings={}
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,_=setup(directory)
        if '--trace' in sys.argv:
            from langchain_core.callbacks import BaseCallbackHandler
            class Trace(BaseCallbackHandler):
                def on_llm_end(self,response,**kwargs):print('FICTIONAL_MODEL_OUTPUT',response.generations[0][0].text,flush=True)
            agent.llm=agent.llm.model_copy(update={'callbacks':[Trace()]})
        try:
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
                client.post('/session',json={}).raise_for_status()
                one=client.post('/conversations',json={'name':'真实甲'}).json()['id']
                two=client.post('/conversations',json={'name':'真实乙'}).json()['id']
                def chat(identity,text):
                    client.headers['X-Chat-Session']=identity
                    before=time.perf_counter()
                    result=client.post('/chat',json={'message':text,'mode':'chat'}).raise_for_status().json()
                    timings[text]=round(time.perf_counter()-before,3)
                    print(identity[:6],text,result['answer'],flush=True)
                    return result
                chat(one,'我叫李四')
                chat(one,'本聊天的项目代号是蓝杉。请只回复已收到。')
                shared=chat(two,'我叫什么？')
                assert '李四' in shared['answer']
                hidden=chat(two,'另一个聊天的项目代号是什么？不知道请明确说不知道。')
                assert '蓝杉' not in hidden['answer']
                recalled=chat(one,'本聊天的项目代号是什么？')
                assert '蓝杉' in recalled['answer']
                assert '900' in chat(two,'先计算100+200，再将结果乘以3。')['answer']
                with session.app_db() as db:owner=db.execute('SELECT user_id FROM sessions WHERE token_hash=?',(session.hash_token(client.cookies[session.COOKIE_NAME]),)).fetchone()[0]
                state=agent.graph.get_state({'configurable':{'thread_id':'chat:'+two}}).values
                dependent_verified=(len(state.get('execution_records',[]))==2 and all(r['status']=='completed' for r in state['execution_records']))
                print('REAL_DEPENDENCY_TOOL_VALIDATED',dependent_verified,flush=True)
                assert '5' in chat(two,'1+4=?')['answer']
                state=agent.graph.get_state({'configurable':{'thread_id':'chat:'+two}}).values
                assert len(state['execution_records'])==1 and state['execution_records'][0]['tool']=='calculator'
            print('PASS real Ollama shared memory/private recall/isolated history and verified calculator; dependency validation='+str(dependent_verified),json.dumps(timings,ensure_ascii=False),round(time.perf_counter()-started,3),'seconds')
            assert dependent_verified,'真实模型依赖工具未通过：回答900但没有两步成功执行记录；隔离/共享与精确计算子项已通过'
        finally:agent.conn.close()


if __name__=='__main__':
    if '--phase' in sys.argv:restart_phase(sys.argv[-2],sys.argv[-1])
    elif '--restart' in sys.argv:restart()
    elif '--ollama' in sys.argv:real()
    else:run()
