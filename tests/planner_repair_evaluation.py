"""Actual graph/checkpoints: intent, dependent results and conversation isolation."""
import json
import os
import tempfile
import sys
import time
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup
from tests.history_summary_evaluation import Model


def run():
    os.environ['MY_AGENT_RAG_ENABLED']='0'
    real='--ollama' in sys.argv
    started=time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,_=setup(directory)
        if not real:agent.llm=Model()
        try:
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
                client.post('/session',json={}).raise_for_status()
                one=client.post('/conversations',json={'name':'计算甲'}).json()['id']
                two=client.post('/conversations',json={'name':'计算乙'}).json()['id']
                def chat(identity,text):
                    client.headers['X-Chat-Session']=identity
                    reply=client.post('/chat',json={'message':text,'mode':'chat'}).raise_for_status().json()
                    state=agent.graph.get_state({'configurable':{'thread_id':'chat:'+identity}}).values
                    return reply,state
                chat(one,'我叫李四');chat(one,'本聊天的代号是青禾')
                reply,state=chat(one,'先计算100+200，再将结果乘以3。')
                assert '900' in reply['answer'] and [r['result']['result'] for r in state['execution_records']]==[300,900]
                reply,state=chat(one,'再将结果乘以3')
                assert state['execution_records'][0]['args']=={'expression':'(900) * 3'} and '2700' in reply['answer']
                reply,state=chat(two,'再乘以3')
                assert state['plan']['action']=='clarify' and not state['execution_records']
                chat(two,'10+20')
                reply,state=chat(two,'结果再乘以3')
                assert state['execution_records'][0]['args']=={'expression':'(30) * 3'} and '90' in reply['answer']
                client.headers['X-Chat-Session']=two
                client.post('/chat',json={'message':'总结文件','mode':'documents'}).raise_for_status()
                reply,state=chat(two,'再乘以3')
                assert state['plan']['action']=='clarify' and not state['execution_records']
                reply,state=chat(two,'查询当前时间，并计算2+3。')
                assert [r['tool'] for r in state['execution_records']]==['time','calculator']
                assert all(r['status']=='completed' for r in state['execution_records'])
                assert isinstance(state['execution_records'][0]['result'],str)
                assert state['execution_records'][1]['result']['result']==5
                assert not state['execution_records'][1]['depends_on']
                chat(one,'你好')
                reply,state=chat(one,'再乘以3')
                assert state['plan']['action']=='clarify' and not state['execution_records']
                reply,state=chat(one,'只解释1+4的含义，不要计算')
                assert state['plan']['action']=='chat' and not state['execution_records']
                print('PASS', 'real Ollama' if real else 'substitute', 'actual graph: history/current intent, two-step real outputs, numeric followup, no stale/cross-chat result, independent mixed tools and no-execution chat',round(time.perf_counter()-started,3),'seconds')
        finally:agent.conn.close()


if __name__=='__main__':run()
