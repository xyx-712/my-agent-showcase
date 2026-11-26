"""One bounded recheck of actual Windows shared-port Uvicorn workers.

Writes a report even on timeout, and returns failure rather than claiming success.
No personal databases, model calls, browser profiles or external tunnels.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx


def create_app():
    import faulthandler
    faulthandler.dump_traceback_later(12,repeat=False)
    from tests.memory_workers_evaluation import create_app as base
    return base()


def run():
    started=time.monotonic()
    report={'passed':False,'mode':'single listen port, uvicorn --workers 2','worker_pids':[],'stage':'startup'}
    output=Path(__file__).resolve().parents[1]/'.demo-runtime'/'shared-worker-recheck';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'MY_AGENT_MODE':'demo','MY_AGENT_PUBLIC_ORIGIN':'https://demo.example',
             'MY_AGENT_DEMO_DATA_DIR':directory,'MY_AGENT_RAG_ENABLED':'0','PYTHONIOENCODING':'utf-8'}
        log=Path(directory,'workers.log').open('w',encoding='utf-8')
        process=subprocess.Popen([sys.executable,'-m','uvicorn','tests.windows_shared_worker_evaluation:create_app','--factory',
            '--host','127.0.0.1','--port',str(port),'--workers','2','--log-level','warning'],env=env,stdout=log,stderr=log)
        try:
            base=f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    if httpx.get(base+'/health',timeout=.5,trust_env=False).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise TimeoutError('test server startup deadline')
            report['stage']='authentication'
            with httpx.Client(base_url=base,headers={'Origin':'https://demo.example'},trust_env=False,timeout=5) as a, \
                 httpx.Client(base_url=base,headers={'Origin':'https://demo.example'},trust_env=False,timeout=5) as b:
                credentials={'username':'shared_port_fictional','password':'fictional-password-123'}
                a.post('/auth/register',json=credentials).raise_for_status();b.post('/auth/login',json=credentials).raise_for_status()
                for client in (a,b):client.headers['Cookie']='__Host-my_agent_session='+client.cookies['__Host-my_agent_session']
                report['stage']='short_connections'
                pids=set()
                for _ in range(40):pids.add(a.get('/worker-id',headers={'Connection':'close'}).raise_for_status().json()['pid'])
                report['worker_pids']=sorted(pids);assert len(pids)==2,pids
                report['stage']='concurrent_chat'
                def send(client,text):return client.post('/chat',json={'message':text,'mode':'chat'})
                with ThreadPoolExecutor(2) as pool:
                    futures=[pool.submit(send,a if i%2==0 else b,text) for i,text in enumerate(('我喜欢足球','我喜欢篮球','我喜欢游泳','我喜欢画画'))]
                    responses=[future.result() for future in futures]
                report['statuses']=[r.status_code for r in responses]
                assert all(r.status_code in (200,409) for r in responses)
                for client in (a,b):client.get('/history').raise_for_status()
                report['passed']=True;report['stage']='completed'
        except Exception as error:
            report['error_type']=type(error).__name__
            report['error']=str(error)[:250]
        finally:
            if process.poll() is None:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                process.wait(timeout=15)
            log.close();time.sleep(.5)
            (output/'workers.log').write_text(Path(directory,'workers.log').read_text(encoding='utf-8',errors='replace'),encoding='utf-8')
    report['elapsed_seconds']=round(time.monotonic()-started,3)
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':run()
