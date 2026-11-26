"""Actual API/checkpoint round-trip with long, fictional history; temporary DBs."""
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tests.vector_index_evaluation import setup
from tests.planner_evaluation import PlanningModel
from src.agent.context import cost,budget


class Model(PlanningModel):
    def __init__(self):super().__init__();self.prompts=[]
    def invoke(self,messages):
        self.prompts.append(messages)
        return super().invoke(messages)


def run():
    with tempfile.TemporaryDirectory() as directory:
        app,agent,session,_=setup(directory)
        model=Model();agent.llm=model
        try:
            with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as client:
                client.post('/session',json={}).raise_for_status()
                from src.server.session import COOKIE_NAME,hash_token
                with session.app_db() as db:
                    owner=db.execute('SELECT user_id FROM sessions WHERE token_hash=?',(hash_token(client.cookies[COOKIE_NAME]),)).fetchone()[0]
                from src.server.history import save_history,get_history
                for i in range(20):
                    save_history(owner,'user',f'old{i}: '+'旧消息'*1200)
                    save_history(owner,'assistant','old reply')
                premise='前提：不能删除任何文件。'+'请保留这一整条消息。'*150
                save_history(owner,'user',premise)
                save_history(owner,'assistant','已确认')
                current='现在怎样继续这个任务？'
                result=client.post('/chat',json={'message':current,'mode':'chat'}).raise_for_status().json()
                assert result['answer']=='普通聊天回复'
                prompt=model.prompts[-1]
                assert sum(m.content==current for m in prompt)==1
                assert any(m.content==premise for m in prompt)
                assert cost(prompt)<=budget().available
                assert len(get_history(owner))==44,'context pruning must not delete saved history'
                saved=agent.graph.get_state({'configurable':{'thread_id':owner}}).values
                # The existing answer node replaces messages with its reply;
                # chat_messages remains the history source, checkpoint the run state.
                assert saved['response']==result['answer']
                # New client with the same server-side identity restores history.
                with TestClient(app,headers={'Origin':'http://127.0.0.1:5173'}) as refreshed:
                    refreshed.cookies.update(client.cookies)
                    refreshed.post('/chat',json={'message':'再说明一下。','mode':'chat'}).raise_for_status()
                assert any(m.content==current for m in model.prompts[-1])
                assert cost(model.prompts[-1])<=budget().available
                from src.agent import document_agent
                from src.agent.context import ContextBudgetError
                from uuid import uuid4
                sources=[{'text':f'fictional source {i}'} for i in range(4)]
                task={'id':uuid4().hex,'kind':'attachments','skill':'document_qa','request':'总结文件',
                      'sources':sources,'file_ids':[],'completed':[]}
                sizes=[]
                def limited_answer(model,batch,request,return_digest=False):
                    sizes.append(len(batch))
                    if len(batch)>1:raise ContextBudgetError('injected assembly budget limit')
                    return 'validated answer',[],'validated digest'
                with patch.object(document_agent,'answer_documents',side_effect=limited_answer):
                    advanced=document_agent.step({'task':task,'user_id':owner,'model':model,'docs':[], 'steps':0,'calls':[]})
                assert sizes==[4,3,2,1]
                assert advanced['task']['qa_offset']==1 and advanced['task']['sources']==sources
            print('PASS long history/current once/full negative premise/unchanged SQLite history/checkpoint and refresh context')
        finally:agent.conn.close()


if __name__=='__main__':run()
