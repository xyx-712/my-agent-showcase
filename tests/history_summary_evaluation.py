"""History condensation API, restart and backup acceptance, fictional data only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup
from tests.rag_planner_evaluation import Model as BaseModel
from tests.test_history_summary import SummaryModel


class Model(BaseModel):
    def __init__(self):super().__init__();self.summary=SummaryModel();self.inputs=[]
    def invoke(self,messages):
        self.inputs.append(messages)
        if '生成有界历史摘要' in messages[0].content:return self.summary.invoke(messages)
        return super().invoke(messages)


def configure():
    os.environ.update(MY_AGENT_RAG_ENABLED='0',MY_AGENT_CONTEXT_TURNS='2',MY_AGENT_SUMMARY_MIN_TURNS='2',MY_AGENT_SUMMARY_BATCH_TURNS='2')


def phase(directory,name):
    configure();app,agent,session,_=setup(directory);model=Model();agent.llm=model
    from src.server.history import save_history
    from src.agent import history_summary as summary
    try:
        with TestClient(app):
            if name=='build':
                user='restart-fictional'
                for text in ('项目青禾不能删除文件','项目决定保留本地部署'):
                    save_history(user,'user',text);save_history(user,'assistant','已确认')
                current=save_history(user,'user','继续')
                initial=summary.update(user,model,current,current,'继续');assert initial['revision']==1
                for text in ('项目还有接口验收未完成','项目决定暂不发布'):
                    save_history(user,'user',text);save_history(user,'assistant','已确认')
                current=save_history(user,'user','继续')
                with session.app_db() as db:db.execute("UPDATE history_summaries SET status='INDEXING',worker_token='crashed',lease_until=0 WHERE user_id=?",(user,))
                Path(directory,'summary-phase.json').write_text(json.dumps({'user':user,'current':current,'end':initial['end_id']}))
            else:
                saved=json.loads(Path(directory,'summary-phase.json').read_text());user=saved['user']
                if name=='resume':
                    recovered=summary.update(user,model,saved['current'],saved['current'],'继续')
                    assert recovered['revision']==2 and len(model.summary.calls)==1
                    assert all(m['id']>saved['end'] for g in model.summary.calls[0]['turns'] for m in g)
                else:
                    assert summary.load(user)['revision']==2
                    assert model.summary.calls==[]
            print('PASS fresh process summary',name)
    finally:agent.conn.close()


def run():
    configure()
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,_=setup(directory);model=Model();agent.llm=model
        from src.server.history import save_history,get_history
        from src.agent import history_summary as summary
        from src.server.backup import backup,restore
        from src.memory.store import memory_store
        from src.agent.context import cost,budget
        headers={'Origin':'http://127.0.0.1:5173'}
        try:
            with TestClient(app,headers=headers) as a:
                b=TestClient(app,headers=headers)
                a.post('/session',json={}).raise_for_status();b.post('/session',json={}).raise_for_status()
                with session.app_db() as db:user=db.execute('SELECT user_id FROM sessions WHERE token_hash=?',(session.hash_token(a.cookies[session.COOKIE_NAME]),)).fetchone()[0]
                original=[]
                for text in ('项目青禾背景：保留本地离线能力','项目决定：禁止删除原始文件','最近一个问题','最近另一个问题'):
                    original.append(save_history(user,'user',text));save_history(user,'assistant','已收到')
                def chat(text):return a.post('/chat',json={'message':text,'mode':'chat'}).raise_for_status().json()
                chat('项目最早的约束是什么？')
                state=agent.graph.get_state({'configurable':{'thread_id':user}}).values
                first=state['history_summary'];assert first and first['end_id']<original[2]
                answer_prompt=model.answers[-1]
                assert any('禁止删除原始文件' in m.content and '较早对话摘要' in m.content for m in answer_prompt)
                assert cost(answer_prompt)<=budget().available
                assert sum(m.content=='项目最早的约束是什么？' for m in answer_prompt)==1
                plan_inputs=[json.loads(m[-1].content) for m in model.inputs if '规划普通聊天任务' in m[0].content]
                assert plan_inputs[-1]['history_summary']['revision']==1
                assert summary.load('other') is None
                b.post('/chat',json={'message':'你好','mode':'chat'}).raise_for_status()
                with session.app_db() as db:other=db.execute('SELECT user_id FROM sessions WHERE token_hash=?',(session.hash_token(b.cookies[session.COOKIE_NAME]),)).fetchone()[0]
                assert not agent.graph.get_state({'configurable':{'thread_id':other}}).values.get('history_summary')
                # Failure leaves original window and the committed cursor intact.
                chat('再补充说明');model.summary.bad=True
                chat('继续解释')
                with session.app_db() as db:failed=summary.row(db,user)
                assert failed['status']=='FAILED' and failed['revision']==1
                assert not any('较早对话摘要' in m.content for m in model.answers[-1])
                model.summary.bad=False;chat('重试历史摘要')
                assert summary.load(user)['revision']==2
                chat('更正，项目决定改为只读演示，不再沿用旧决定。')
                assert summary.load(user) is None and summary.live(user,first) is None
                memory_store.save(user,'name','李四')
                item=memory_store.inspect(user,'name')
                a.request('DELETE',f"/memories/{item['id']}",json={'revision':item['revision']}).raise_for_status()
                chat('你好')
                assert memory_store.get(user,'name') is None and summary.live(user,first) is None
                # Keep a completed summary for full three-database restore validation.
                for text in ('项目现在只有只读界面','项目未完成事项是验收报告'):
                    save_history(user,'user',text);save_history(user,'assistant','已收到')
                current=save_history(user,'user','继续')
                restored_expected=summary.update(user,model,current,current,'继续',force=True)
                assert restored_expected
                history=get_history(user)
                snapshot=Path(directory)/'backup';backup(snapshot)
            agent.conn.close();restore(snapshot,True)
            assert summary.load(user)==restored_expected and get_history(user)==history
            assert memory_store.get(user,'name') is None
            print('PASS API long context/Planner/quoted constraint/current once, failure fallback/retry, correction/delete/checkpoint fences, isolation and summary+history backup restore')
        finally:agent.conn.close()
    # Each subprocess binds isolated paths before importing the API/store.
    with tempfile.TemporaryDirectory() as directory:
        for name in ('build','resume','read'):
            subprocess.run([sys.executable,'-X','utf8','-m','tests.history_summary_evaluation','--phase',directory,name],check=True,timeout=45)


def real():
    configure()
    os.environ['MY_AGENT_MODEL']='qwen2.5:7b'
    os.environ['MY_AGENT_OLLAMA_URL']='http://127.0.0.1:11434'
    started=time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,_=setup(directory)
        from src.server.history import save_history
        from src.agent.history_summary import load
        try:
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
                client.post('/session',json={}).raise_for_status()
                with session.app_db() as db:user=db.execute('SELECT user_id FROM sessions WHERE token_hash=?',(session.hash_token(client.cookies[session.COOKIE_NAME]),)).fetchone()[0]
                for text in ('项目叫青禾，演示必须在本地离线运行。','项目决定：禁止删除原始文件，还有界面验收未完成。','今天先聊界面颜色','刚才只是随便聊聊'):
                    save_history(user,'user',text);save_history(user,'assistant','已收到')
                response=client.post('/chat',json={'message':'之前确定的项目叫什么？演示要求是什么？','mode':'chat'}).raise_for_status().json()
                digest=load(user)
                assert digest and digest['end_id']==4,digest
                print('REAL_SUMMARY',json.dumps(digest,ensure_ascii=False),flush=True)
                print('REAL_ANSWER',response['answer'],flush=True)
                assert '青禾' in response['answer'] and ('本地' in response['answer'] or '离线' in response['answer'])
                client.post('/chat',json={'message':'更正，项目改为白榆，只做只读演示。','mode':'chat'}).raise_for_status()
                corrected=client.post('/chat',json={'message':'现在项目叫什么？','mode':'chat'}).raise_for_status().json()
                print('REAL_CORRECTION',corrected['answer'],flush=True)
                assert '白榆' in corrected['answer'] and '青禾' not in corrected['answer']
            print('PASS real Qwen2.5:7b long-history condensation/answer/correction',round(time.perf_counter()-started,3),'seconds')
        finally:agent.conn.close()


if __name__=='__main__':
    if '--phase' in sys.argv:phase(sys.argv[-2],sys.argv[-1])
    elif '--ollama' in sys.argv:real()
    else:run()
