"""Two actual FastAPI workers, fictional account, isolated Demo databases."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import httpx


def create_app():
    from tests.multiworker_evaluation import create_app as original
    app=original()
    @app.middleware('http')
    async def test_worker_header(request,call_next):
        response=await call_next(request)
        response.headers['X-Test-Worker']=str(os.getpid())
        return response
    return app


def run(extra=None):
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'MY_AGENT_MODE':'demo','MY_AGENT_PUBLIC_ORIGIN':'https://demo.example',
             'MY_AGENT_DEMO_DATA_DIR':directory,'PYTHONIOENCODING':'utf-8','NO_PROXY':'127.0.0.1,localhost'}
        log=(Path(directory)/'workers.log').open('w',encoding='utf-8')
        process=subprocess.Popen([sys.executable,'-m','uvicorn','tests.memory_workers_evaluation:create_app','--factory',
            '--host','127.0.0.1','--port',str(port),'--workers','2','--log-level','warning'],env=env,stdout=log,stderr=log)
        base=f'http://127.0.0.1:{port}'
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                try:
                    if httpx.get(base+'/health',timeout=1,trust_env=False).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise AssertionError('test server startup timed out')
            with httpx.Client(base_url=base,headers={'Origin':'https://demo.example'},trust_env=False,timeout=30) as a, \
                 httpx.Client(base_url=base,headers={'Origin':'https://demo.example'},trust_env=False,timeout=30) as b:
                payload={'username':'memory_worker_user','password':'fictional-password-123'}
                a.post('/auth/register',json=payload).raise_for_status()
                b.post('/auth/login',json=payload).raise_for_status()
                for client in (a,b):client.headers['Cookie']='__Host-my_agent_session='+client.cookies['__Host-my_agent_session']
                pids={a.get('/worker-id',headers={'Connection':'close'}).raise_for_status().json()['pid'] for _ in range(40)}
                assert len(pids)==2,pids
                first_pid=a.get('/worker-id').raise_for_status().json()['pid']
                for _ in range(40):
                    second_pid=b.get('/worker-id').raise_for_status().json()['pid']
                    if second_pid!=first_pid:break
                    b.get('/worker-id',headers={'Connection':'close'}).raise_for_status()
                else:raise AssertionError('could not pin clients to distinct API workers')
                statuses=[]
                successful_pids=[]
                def send(client,text):
                    for attempt in range(10):
                        response=client.post('/chat',json={'message':text,'mode':'chat'})
                        statuses.append(response.status_code)
                        if response.status_code==409:time.sleep(.15);continue
                        response.raise_for_status();successful_pids.append(int(response.headers['X-Test-Worker']));return response.json()
                    raise AssertionError('bounded conflict retry exhausted')
                values=['足球','篮球','游泳','画画']
                with ThreadPoolExecutor(2) as pool:
                    futures=[pool.submit(send,a if i%2==0 else b,'我喜欢'+value) for i,value in enumerate(values)]
                    for future in futures:future.result()
                initial_pids=set(successful_pids)
                assert len(initial_pids)==2 and initial_pids<=pids,initial_pids
                with closing(sqlite3.connect(Path(directory)/'memory.db')) as memory,closing(sqlite3.connect(Path(directory)/'app.db')) as app:
                    owner,value,revision=memory.execute("SELECT user_id,value,revision FROM memories WHERE key='hobby'").fetchone()
                    assert set(value.split('、'))==set(values) and revision==4,(value,revision)
                    source_ids=[row[0] for row in memory.execute('SELECT source_message_id FROM memory_events')]
                    assert len(source_ids)==4
                    for identity in source_ids:
                        assert app.execute('SELECT user_id,role FROM chat_messages WHERE id=?',(identity,)).fetchone()==(owner,'user')
                send(a,'忘记我的爱好')
                send(b,'我喜欢足球')
                with closing(sqlite3.connect(Path(directory)/'memory.db')) as memory:
                    assert memory.execute("SELECT status FROM memories WHERE key='hobby'").fetchone()[0]=='deleted'
                send(b,'重新记住我喜欢足球')
                with closing(sqlite3.connect(Path(directory)/'memory.db')) as memory:
                    assert memory.execute("SELECT value,status FROM memories WHERE key='hobby'").fetchone()==('足球','active')
                print(json.dumps({'worker_pids':sorted(pids),'initial_write_worker_pids':sorted(initial_pids),'request_statuses':dict(Counter(statuses)),
                    'initial_successful_memory_writes':4,'source_links':4,'lost_updates':0,
                    'delete_barrier':'blocked ordinary save; explicit newer restore accepted'},ensure_ascii=False),flush=True)
                print('PASS two real API workers concurrent memory merge, provenance and cross-browser delete protection')
                if extra:extra(a,b)
        finally:
            if process.poll() is None:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                process.wait(timeout=15);time.sleep(1)
            log.close()


if __name__=='__main__':run()
