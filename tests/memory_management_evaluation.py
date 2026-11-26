"""Real authenticated API/policy/backup; fictional data and isolated databases."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup,FakeVectors,close_test_chroma
from tests.rag_planner_evaluation import Model


def run():
    os.environ['MY_AGENT_RAG_ENABLED']='0'
    os.environ['MY_AGENT_EMBEDDING_MODEL']='fake-embeddings'
    os.environ.pop('MY_AGENT_CHROMA_URL',None)
    os.environ.pop('MY_AGENT_CHROMA_DIR',None)
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,Service=setup(directory)
        agent.llm=Model()
        from src.memory.store import memory_store
        from src.agent.memory_node import memory_extractor_node
        from langchain_core.messages import HumanMessage
        from src.server.backup import backup,restore
        headers={'Origin':'http://127.0.0.1:5173'}
        try:
            with TestClient(app,headers=headers) as a:
                b=TestClient(app,headers=headers)
                for client in (a,b):client.post('/session',json={}).raise_for_status()
                def chat(text,mode='chat'):
                    return a.post('/chat',json={'message':text,'mode':mode}).raise_for_status().json()
                chat('我叫李四')
                first=a.get('/memories').raise_for_status().json()['items'][0]
                owner=first['user_id'];identity=first['id'];path=f'/memories/{identity}'
                assert first['value']=='李四' and first['revision']==1
                detail=a.get(path).raise_for_status().json()
                assert detail['source']['content']=='我叫李四' and len(detail['versions'])==1
                assert b.get(path).status_code==404
                for method,payload in [('patch',{'revision':1,'value':'越权'}),('delete',{'revision':1})]:
                    assert b.request(method,path,json=payload).status_code==404
                assert a.get('/memories?user_id=other').status_code==422
                assert a.patch(path,json={'revision':1,'value':'王五','user_id':'other'}).status_code==422
                assert a.patch(path,json={'revision':'1','value':'王五'}).status_code==422
                assert a.get('/memories/'+str(2**80)).status_code==422
                assert a.patch(path,json={'revision':2**80,'value':'王五'}).status_code==422
                assert a.patch(path,json={'revision':1,'value':' '}).status_code==422
                assert a.patch(path,json={'revision':1,'value':'王五'},headers={'Origin':'https://evil.example'}).status_code==403
                assert TestClient(app).get('/memories').status_code==401
                changed=a.patch(path,json={'revision':1,'value':'王五'}).raise_for_status().json()['item']
                assert changed['revision']==2 and changed['source_type']=='user_management'
                assert changed['source_message_id'] is None and changed['value']=='王五'
                details=a.get(path).raise_for_status().json()
                assert details['source']['type']=='management'
                assert [v['value'] for v in details['versions']]==['王五','李四']
                assert a.patch(path,json={'revision':1,'value':'赵六'}).status_code==409
                old={'user_id':owner,'source_message_id':first['source_message_id'],'memory_generation':0,'messages':[HumanMessage(content='我叫李四')]}
                memory_extractor_node(old)
                assert memory_store.get(owner,'name')=='王五'
                auto=a.get('/memories/settings').json()
                assert auto=={'automatic_enabled':True,'revision':1}
                paused=a.patch('/memories/settings',json={'automatic_enabled':False,'revision':auto['revision']}).raise_for_status().json()
                assert not paused['automatic_enabled']
                assert a.patch('/memories/settings',json={'automatic_enabled':True,'revision':1}).status_code==409
                with patch('src.memory.extractor.extract_operations',side_effect=AssertionError('paused extraction ran')):
                    assert chat('我喜欢苹果')['answer']
                    assert '900' in chat('先计算100+200，再将结果乘以3。')['answer']
                assert memory_store.get(owner,'hobby') is None and memory_store.get(owner,'name')=='王五'
                manual=a.patch(path,json={'revision':2,'value':'孙七'}).raise_for_status().json()
                assert manual['item']['value']=='孙七' and not manual['settings']['automatic_enabled']
                doc=a.post('/documents',files={'file':('fictional-leave.txt','员工每年享有十五天带薪年假，休假提前三天向主管申请。'.encode())}).raise_for_status().json()['id']
                service=Service(backend_factory=FakeVectors);service.run_once()
                from src.retrieval.service import statuses
                assert statuses(owner)[doc]['status']=='READY',statuses(owner)
                with patch('src.retrieval.service.enabled',return_value=True),patch('src.retrieval.qa.IndexService',return_value=service):
                    result=chat('根据文件，员工休假有几天？','documents')
                    assert result['citations'] and result['citations'][0]['file_id']==doc,result
                    planned=chat('员工年假有几天，向谁申请？','auto')
                    assert planned['citations'] and 'semantic_search' in planned['tool_calls'],planned
                assert memory_store.get(owner,'hobby') is None
                current=a.get('/memories/settings').json()
                a.patch('/memories/settings',json={'automatic_enabled':True,'revision':current['revision']}).raise_for_status()
                chat('我喜欢篮球')
                assert memory_store.get(owner,'hobby')=='篮球'
                # UI deletion fences old checkpoint, unsourced legacy callback and delayed messages.
                a.request('DELETE',path,json={'revision':3}).raise_for_status()
                assert memory_store.get(owner,'name') is None
                assert all(row['key']!='name' for row in a.get('/memories').json()['items'])
                assert any(row['key']=='name' for row in a.get('/memories?include_deleted=true').json()['items'])
                assert a.patch(path,json={'revision':4,'value':'李四'}).status_code==409
                assert a.request('DELETE',path,json={'revision':3}).status_code==409
                memory_extractor_node(old);memory_store.save(owner,'name','孙七')
                assert memory_store.get(owner,'name') is None
                assert all(key!='name' for key,value in memory_store.search(owner))
                assert b.get('/memories').json()['items']==[]
                saved=a.get('/memories/settings').json()
                a.patch('/memories/settings',json={'automatic_enabled':False,'revision':saved['revision']}).raise_for_status()
                saved=a.get('/memories/settings').json()
                # A second authenticated client is equivalent to reloading the page.
                with TestClient(app,headers=headers) as refreshed:
                    refreshed.cookies.update(a.cookies)
                    assert refreshed.get('/memories/settings').json()==saved
                    assert refreshed.get(path).json()['item']['status']=='deleted'
                snapshot=Path(directory)/'snapshot';backup(snapshot)
                with session.app_db() as db:
                    db.execute('UPDATE sessions SET expires_at=0 WHERE user_id=?',(owner,))
                assert a.get('/memories').status_code==401
            agent.conn.close()
            restore(snapshot,True)
            assert memory_store.auto_settings(owner)==saved
            assert memory_store.get(owner,'name') is None
            with closing(sqlite3.connect(memory_store.db)) as db:
                assert db.execute('SELECT count(*) FROM memory_management_actions WHERE user_id=?',(owner,)).fetchone()[0]==3
                assert db.execute("SELECT count(*) FROM memory_revisions WHERE user_id=? AND key='name'",(owner,)).fetchone()[0]==4
            print('PASS memory APIs, strict auth/Origin/ownership, CAS/history/source, pause+chat/tools/RAG, resume, delete/replay, refresh/expiry, backup+restore')
        finally:
            agent.conn.close();close_test_chroma()


if __name__=='__main__':run()
