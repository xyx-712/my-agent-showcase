"""Actual two-worker summary acceptance; probe exists in this test factory only."""
from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4
from fastapi import Depends
from tests.history_summary_evaluation import Model
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx


def create_app():
    from tests.memory_workers_evaluation import create_app as base
    from src.server.api import general_agent
    from src.server.session import require_user,app_db
    from src.agent import history_summary as summary
    app=base();general_agent.llm=Model()
    def probe(user=Depends(require_user)):
        with app_db() as db:
            current=summary.row(db,user)
            revisions=db.execute('SELECT revision,end_id FROM history_summary_revisions WHERE user_id=? ORDER BY revision',(user,)).fetchall()
        return {'row':current,'revisions':revisions,'worker':os.getpid()}
    from fastapi.routing import APIRoute
    app.router.routes.insert(0,APIRoute('/test-summary-probe',probe,methods=['GET']))
    return app


def acceptance(a,b):
    for i in range(6):
        a.post('/chat',json={'message':f'项目青禾第{i}项决定是保留本地验收。','mode':'chat'}).raise_for_status()
    before=a.get('/test-summary-probe').raise_for_status().json()
    assert before['row']['status']=='READY'
    # One idempotency key across actual distinct processes: no duplicate summary batch.
    payload={'message':'请回顾项目背景','mode':'chat','request_id':str(uuid4())}
    with ThreadPoolExecutor(2) as pool:
        responses=[pool.submit(c.post,'/chat',json=payload) for c in (a,b)]
        results=[r.result() for r in responses]
    assert all(r.status_code in (200,409) for r in results),[(r.status_code,r.text) for r in results]
    assert len({r.headers['X-Test-Worker'] for r in results})==2
    a.post('/chat',json=payload).raise_for_status()
    one=a.get('/test-summary-probe').json();two=b.get('/test-summary-probe').json()
    assert one['row']==two['row'] and one['row']['status']=='READY'
    versions=one['revisions'];assert len({version['end_id'] for version in versions})==len(versions)
    assert [version['revision'] for version in versions]==list(range(1,len(versions)+1))
    assert one['row']['revision']<=before['row']['revision']+1
    print('PASS two real workers: shared summary/CAS/monotonic ranges, concurrent idempotent request and no duplicate batch', [r.status_code for r in results])


def run(extra=None):
    # Independent listen sockets avoid the previously observed Windows shared
    # listener timeout. This verifies two API processes, not shared-listen stress.
    with tempfile.TemporaryDirectory() as directory:
        env={**os.environ,'MY_AGENT_MODE':'demo','MY_AGENT_PUBLIC_ORIGIN':'https://demo.example',
             'MY_AGENT_DEMO_DATA_DIR':directory,'PYTHONIOENCODING':'utf-8','MY_AGENT_CONTEXT_TURNS':'2',
             'MY_AGENT_SUMMARY_MIN_TURNS':'2','MY_AGENT_SUMMARY_BATCH_TURNS':'2','MY_AGENT_RAG_ENABLED':'0'}
        servers=[];clients=[];logs=[]
        try:
            for index in range(2):
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                log=Path(directory,f'worker-{index}.log').open('w',encoding='utf-8');logs.append(log)
                process=subprocess.Popen([sys.executable,'-m','uvicorn','tests.history_summary_workers_evaluation:create_app','--factory',
                    '--host','127.0.0.1','--port',str(port),'--workers','1','--log-level','warning'],env=env,stdout=log,stderr=log)
                servers.append(process)
                client=httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Origin':'https://demo.example'},trust_env=False,timeout=15)
                clients.append(client)
                for _ in range(150):
                    try:
                        if client.get('/health',timeout=.5).status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise AssertionError('temporary worker startup timeout')
            a,b=clients
            credentials={'username':'summary_workers','password':'fictional-password-123'}
            a.post('/auth/register',json=credentials).raise_for_status();b.post('/auth/login',json=credentials).raise_for_status()
            for client in clients:client.headers['Cookie']='__Host-my_agent_session='+client.cookies['__Host-my_agent_session']
            assert a.get('/worker-id').json()['pid']!=b.get('/worker-id').json()['pid']
            acceptance(a,b)
            if extra:extra(a,b)
        finally:
            for client in clients:client.close()
            for process in servers:
                if process.poll() is None:
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    process.wait(timeout=15)
            for log in logs:log.close()
            time.sleep(.5)


if __name__=='__main__':run()
