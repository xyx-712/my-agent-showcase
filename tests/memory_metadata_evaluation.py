"""End-to-end memory metadata/provenance/delete/backup acceptance with fictional data."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from tests.vector_index_evaluation import setup
from tests.planner_evaluation import PlanningModel


def run():
    with tempfile.TemporaryDirectory() as directory:
        with closing(sqlite3.connect(Path(directory)/'MEMORY_DB.db')) as legacy,legacy:
            legacy.execute('CREATE TABLE memories(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,UNIQUE(user_id,key))')
            legacy.execute("INSERT INTO memories VALUES(42,'fictional-legacy','name','旧资料')")
        app,agent,session,_=setup(directory)
        agent.llm=PlanningModel()
        from src.memory.store import memory_store
        from src.server.history import memory_source
        from src.server.backup import backup,restore
        from src.agent.memory_node import memory_extractor_node
        old=memory_store.inspect('fictional-legacy','name')
        assert old['id']==42 and old['value']=='旧资料' and old['source_type']=='legacy'
        assert old['source_message_id'] is None and old['created_at'] is None and old['confirmation_state']=='unknown'
        headers={'Origin':'http://127.0.0.1:5173'}
        with TestClient(app,headers=headers) as c,TestClient(app,headers=headers) as other:
            for client in (c,other):client.post('/session',json={}).raise_for_status()
            def identity(client):
                with session.app_db() as db:
                    return db.execute('SELECT user_id FROM sessions WHERE token_hash=?',(session.hash_token(client.cookies[session.COOKIE_NAME]),)).fetchone()[0]
            owner,foreign=identity(c),identity(other)
            def send(text,client=c):return client.post('/chat',json={'message':text,'mode':'chat'}).raise_for_status().json()
            send('我叫李四')
            first=memory_store.inspect(owner,'name')
            assert memory_source(owner,first['source_message_id'])=={'role':'user','content':'我叫李四'}
            assert first['source_type']=='user_statement'
            conflict=send('我的名字是王五')
            assert '确认' in conflict['answer']
            assert memory_store.get(owner,'name')=='李四'
            assert memory_store.inspect(owner,'name')['status']=='pending_confirmation'
            send('更正，我的名字是王五')
            assert memory_store.get(owner,'name')=='王五'
            assert memory_store.inspect(owner,'name')['confirmation_state']=='user_confirmed'
            revision=memory_store.inspect(owner,'name')['revision']
            for text in ('他说“我叫赵六”','假设我叫赵六','请扮演，我是软件工程师'):
                send(text)
                assert memory_store.inspect(owner,'name')['revision']==revision
            for text in ['他说“我叫赵六”','假设我叫赵六','请扮演赵六，我叫赵六','今天我喜欢苹果']:
                send(text)
                assert memory_store.inspect(owner,'name')['revision']==revision
            send('我喜欢篮球、苹果')
            hobby=memory_store.inspect(owner,'hobby')
            send('我现在不喜欢苹果了，我喜欢香蕉')
            assert memory_store.get(owner,'hobby')=='篮球、香蕉'
            memory_extractor_node({'user_id':owner,'source_message_id':hobby['source_message_id'],
                'messages':[HumanMessage(content='我喜欢篮球、苹果')]})
            assert memory_store.get(owner,'hobby')=='篮球、香蕉'
            send('我叫钱八',other)
            assert memory_store.get(foreign,'name')=='钱八'
            try:
                memory_store.save(foreign,'name','李四',source_id=first['source_message_id'],text='我叫李四',source_type='user_statement')
                raise AssertionError('foreign provenance accepted')
            except ValueError:pass
            assert c.post('/chat',json={'message':'我叫伪造','source_message_id':first['source_message_id']}).status_code==422
            send('我的职业是医生')
            send('我的职业是教师')
            assert memory_store.get(owner,'job')=='医生' and 'job' in memory_store.pending_keys(owner)
            uploaded=c.post('/documents',files={'file':('fictional.txt','简历中的人物叫赵六，职业是教师。'.encode())}).raise_for_status().json()['id']
            c.post('/chat',json={'message':'总结文件','mode':'documents'}).raise_for_status()
            assert memory_store.get(owner,'name')=='王五' and memory_store.get(owner,'job')=='医生'
            send('忘记我的名字')
            deleted=memory_store.inspect(owner,'name')
            assert deleted['status']=='deleted' and memory_store.get(owner,'name') is None
            assert all(key!='name' for key,value in memory_store.search(owner))
            memory_store.save(owner,'name','王五')
            assert memory_store.inspect(owner,'name')['revision']==deleted['revision']
            send('重新记住我的名字是王五')
            assert memory_store.get(owner,'name')=='王五'
            send('更正，我的名字是孙七')
            assert memory_store.get(owner,'name')=='孙七'
            send('忘记我的名字')
            deleted=memory_store.inspect(owner,'name')
            snapshot=Path(directory)/'snapshot'
            backup(snapshot)
        agent.conn.close()
        memory_store.save(owner,'later','not in snapshot')
        restore(snapshot,True)
        assert memory_store.inspect(owner,'name')==deleted
        assert memory_store.get(owner,'name') is None and memory_store.get(owner,'later') is None
        assert memory_store.get(owner,'job')=='医生' and 'job' in memory_store.pending_keys(owner)
        memory_store.save(owner,'name','孙七')
        assert memory_store.get(owner,'name') is None
        assert memory_source(owner,deleted['last_message_id'])['content']=='忘记我的名字'
        from unittest.mock import patch
        from src.memory.policy import MemoryPolicy
        original=MemoryPolicy.apply
        def during_write(policy,*args,**kwargs):
            try:
                backup(Path(directory)/'must-not-publish')
                raise AssertionError('backup allowed during memory write')
            except RuntimeError:pass
            return original(policy,*args,**kwargs)
        with patch.object(MemoryPolicy,'apply',during_write):memory_store.save(owner,'name','孙七')
        print('PASS real API source IDs/owner checks, statement/correction/conflict, quotes/hypotheses, partial delete, stale checkpoint, explicit restore, attachment isolation and metadata/tombstone/candidate backup restore')


if __name__=='__main__':run()
