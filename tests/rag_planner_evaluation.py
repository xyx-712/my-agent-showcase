"""API -> Planner -> existing graph/document workflow integration, isolated sources."""
import json
import os
import tempfile
import sys
from unittest.mock import patch
from langchain_core.messages import AIMessage
from fastapi.testclient import TestClient
from tests.vector_index_evaluation import setup, FakeVectors, close_test_chroma
from tests.planner_evaluation import PlanningModel


class Model(PlanningModel):
    def invoke(self,messages):
        system=messages[0].content
        if '规划普通聊天任务' in system:
            text=json.loads(messages[-1].content)['messages'][-1]['content']
            action='knowledge' if ('休假' in text or '年假' in text or '退款' in text) else 'document' if '总结' in text else None
            if action:
                return AIMessage(content=json.dumps({'action':action,'steps':[],'question':''}))
        data=json.loads(messages[-1].content) if 'Schema:' in system else {}
        if isinstance(data,dict) and 'question_parts' in data:
            return AIMessage(content=json.dumps({'answerable':True,'items':[],'synthesis':[],
                'coverage':[{'part':p['part'],'missing':False,'answer':'；'.join(s['text'] for s in data['sources']),
                'evidence':[{'source':i,'quote':s['text']} for i,s in enumerate(data['sources'])]} for p in data['question_parts']]}))
        return super().invoke(messages)


def run():
    real = '--real' in sys.argv
    os.environ['MY_AGENT_RAG_ENABLED']='0'
    os.environ['MY_AGENT_EMBEDDING_MODEL']='embeddinggemma' if real else 'fake-embeddings'
    os.environ.pop('MY_AGENT_CHROMA_DIR',None)
    os.environ.pop('MY_AGENT_CHROMA_URL',None)
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,Service=setup(directory)
        if not real:
            agent.llm=Model()
        service=Service() if real else Service(backend_factory=FakeVectors)
        try:
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as c:
                c.post('/session',json={}).raise_for_status()
                identity=c.post('/documents',files={'file':('leave.txt','员工每年享有十五天带薪年假，休假须提前三天向直属主管提交申请。'.encode())}).raise_for_status().json()['id']
                service.run_once()
                with patch('src.retrieval.service.enabled',return_value=True),patch('src.retrieval.qa.IndexService',return_value=service):
                    def chat(text,mode='auto'):
                        return c.post('/chat',json={'message':text,'mode':mode}).raise_for_status().json()
                    result=chat('根据上传文件，员工年假有几天，找谁申请？')
                    assert result['citations'] and result['citations'][0]['file_id']==identity,result
                    with session.app_db() as db:
                        owner=db.execute('SELECT user_id FROM documents WHERE id=?',(identity,)).fetchone()[0]
                    state=agent.graph.get_state({'configurable':{'thread_id':owner}}).values
                    assert state['plan']['action']=='knowledge' and 'semantic_search' in result['tool_calls'], (state['plan'],result)
                    if not real:
                        second=c.post('/documents',files={'file':('approval.txt','年假申请由主管批准，休假提前三天申请。'.encode())}).raise_for_status().json()['id']
                        service.run_once()
                        joint=chat('年假与休假申请规定是什么？')
                        assert {citation['file_id'] for citation in joint['citations']}=={identity,second}, joint
                        with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as other:
                            other.post('/session',json={}).raise_for_status()
                            hidden=other.post('/chat',json={'message':'年假需要找谁申请？'}).raise_for_status().json()
                            assert not hidden['citations']
                            assert other.get('/documents/'+identity).status_code==404
                        c.delete('/documents/'+second).raise_for_status()
                    result=chat('你好')
                    assert not result['citations'] and (real or result['answer']=='普通聊天回复')
                    assert not chat('休假随便聊聊','chat')['citations']
                    assert '5' in chat('1+4=?')['answer']
                    assert '900' in chat('先计算100+200，再将结果乘以3。')['answer']
                    result=chat('总结全部文件')
                    assert result['citations'] and 'semantic_search' not in result['tool_calls'], result
                    assert agent.graph.get_state({'configurable':{'thread_id':owner}}).values['plan']['action']=='document'
                    c.delete('/documents/'+identity).raise_for_status()
                    assert not chat('休假需要找谁申请？')['citations']
            print('PASS API auto Planner knowledge/document nodes, shared RAG, citations reset, chat override, single/dependent tools, full summary and deleted source')
        finally:
            agent.conn.close()
            close_test_chroma()


if __name__=='__main__': run()
