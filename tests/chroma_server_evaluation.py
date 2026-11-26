"""Two real API workers + a real local Chroma server, only fictional temp data."""
import concurrent.futures
from contextlib import contextmanager, closing
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
    from tests.multiworker_evaluation import create_app as original
    app=original()
    os.environ['MY_AGENT_RAG_ENABLED']='1'
    return app


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


@contextmanager
def isolated_directory():
    temporary=tempfile.TemporaryDirectory()
    try:yield temporary.name
    finally:
        assert Path(temporary.name).resolve().parent==Path(tempfile.gettempdir()).resolve()
        for attempt in range(3):
            try:
                temporary.cleanup()
                break
            except OSError:
                if attempt==2:raise
                time.sleep(1)


def run():
    results={}
    with isolated_directory() as tmp:
        directory=Path(tmp)
        cp,ap=port(),port()
        env={**os.environ,'NO_PROXY':'127.0.0.1,localhost','PYTHONIOENCODING':'utf-8','MY_AGENT_MODE':'demo','MY_AGENT_PUBLIC_ORIGIN':'https://demo.example',
             'MY_AGENT_DEMO_DATA_DIR':str(directory/'business'),'MY_AGENT_CHROMA_URL':f'http://127.0.0.1:{cp}',
             'MY_AGENT_EMBEDDING_MODEL':'embeddinggemma','MY_AGENT_EMBEDDING_URL':'http://127.0.0.1:11434'}
        chroma=None; api=None
        log=(directory/'process.log').open('w',encoding='utf-8')
        def start_chroma():
            return subprocess.Popen([str(Path(sys.executable).with_name('chroma.exe')),'run','--host','127.0.0.1','--port',str(cp),'--path',str(directory/'vectors')],stdout=log,stderr=log)
        def wait_url(url,timeout=60):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                try:
                    if httpx.get(url,timeout=1,trust_env=False).status_code==200:return
                except httpx.HTTPError:pass
                time.sleep(.2)
            raise AssertionError('service did not start: '+url)
        def stop(process):
            if process and process.poll() is None:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                process.wait(timeout=15)
                time.sleep(1)
        try:
            chroma=start_chroma();wait_url(f'http://127.0.0.1:{cp}/api/v2/heartbeat')
            before=time.perf_counter()
            api=subprocess.Popen([sys.executable,'-m','uvicorn','tests.chroma_server_evaluation:create_app','--factory','--host','127.0.0.1','--port',str(ap),'--workers','2','--log-level','warning'],env=env,stdout=log,stderr=log)
            base=f'http://127.0.0.1:{ap}'
            wait_url(base+'/health')
            results['startup_to_health_seconds']=round(time.perf_counter()-before,3)
            @contextmanager
            def client(name):
                c=httpx.Client(base_url=base,headers={'Origin':'https://demo.example'},timeout=45,trust_env=False)
                c.post('/auth/register',json={'username':name,'password':'fictional-password-123'}).raise_for_status()
                c.headers['Cookie']='__Host-my_agent_session='+c.cookies['__Host-my_agent_session']
                try:yield c
                finally:c.close()
            with client('server_a') as a,client('server_b') as b:
                def upload(c,name):
                    return c.post('/documents',files={'file':(name,'员工每年享有十五天带薪年假，休假须提前三天向直属主管提交申请。'.encode())}).raise_for_status().json()['id']
                before=time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    fa=pool.submit(upload,a,'a.txt');fb=pool.submit(upload,b,'b.txt')
                    da,db=fa.result(),fb.result()
                def ready(c,identity):
                    deadline=time.monotonic()+90
                    while time.monotonic()<deadline:
                        row=next(d for d in c.get('/documents').raise_for_status().json()['files'] if d['id']==identity)['index']
                        if row['status']=='READY':return row
                        assert row['status']!='FAILED',row
                        time.sleep(.3)
                    raise AssertionError('index stalled')
                rowa,rowb=ready(a,da),ready(b,db)
                results['two_owners_index_seconds']=round(time.perf_counter()-before,3)
                pids={a.get('/worker-id',headers={'Connection':'close'}).json()['pid'] for _ in range(40)}
                assert len(pids)==2,pids
                results['api_worker_pids']=sorted(pids)
                def search(c,identity):
                    return c.post('/retrieval/search',json={'query':'员工年假有几天，找谁申请？','document_ids':[identity],'top_k':4})
                before=time.perf_counter();hits=search(a,da).raise_for_status().json()['hits']
                results['retrieval_including_embedding_rpc_seconds']=round(time.perf_counter()-before,3)
                assert hits and all(h['document_id']==da for h in hits)
                assert search(b,da).status_code==404
                with concurrent.futures.ThreadPoolExecutor(8) as pool:
                    response=list(pool.map(lambda i:search(a,da) if i%2==0 else search(b,db),range(16)))
                codes={code:sum(r.status_code==code for r in response) for code in {r.status_code for r in response}}
                assert all(r.status_code in (200,409) for r in response),[(r.status_code,r.text) for r in response]
                assert any(r.status_code==200 for r in response)
                assert all(r.json()['hits'] for r in response if r.status_code==200)
                results['concurrent_queries_status_counts']=codes
                before=time.perf_counter();a.post('/chat',json={'message':'你好','mode':'chat'}).raise_for_status()
                results['substitute_chat_seconds']=round(time.perf_counter()-before,3)
                # SQLite generation replacement; only the new complete generation becomes READY.
                before=time.perf_counter();a.post('/documents/'+da+'/reindex',json={}).raise_for_status()
                rebuilt=ready(a,da);assert rebuilt['generation']!=rowa['generation']
                results['rebuild_seconds']=round(time.perf_counter()-before,3)
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    query=pool.submit(search,a,da)
                    deleting=a.delete('/documents/'+da)
                    assert deleting.status_code in (200,409),deleting.text
                    raced=query.result()
                if deleting.status_code==409:
                    a.delete('/documents/'+da).raise_for_status()
                assert raced.status_code in (200,404,409),raced.text
                assert search(a,da).status_code==404
                results['delete_race']={'delete_status':deleting.status_code,'query_status':raced.status_code,'subsequent_search':404}
                stop(chroma)
                assert search(b,db).status_code==503
                assert '5' in b.post('/chat',json={'message':'1+4=?','mode':'chat'}).raise_for_status().json()['answer']
                results['chroma_down']='search 503; calculator remains usable'
                chroma=start_chroma();wait_url(f'http://127.0.0.1:{cp}/api/v2/heartbeat')
                assert search(b,db).raise_for_status().json()['hits']
                assert ready(b,db)['generation']==rowb['generation']
                results['server_restart']='persistent READY generation reused'
                snapshot=directory/'snapshot'
                command=[sys.executable,'-m','src.server.backup']
                for attempt in range(3):
                    copied=subprocess.run([*command,'backup',str(snapshot)],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
                    if copied.returncode==0:break
                    time.sleep(2)
                assert copied.returncode==0,copied.stderr
                refused=subprocess.run([*command,'restore',str(snapshot),'--confirm-restore'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
                assert refused.returncode!=0,'live restore must be refused'
                results['live_restore']='refused while API workers registered'
                stop(api)
                # A hard process-tree stop leaves worker registrations until the
                # real lease timeout; do not forge expiry in an acceptance test.
                print('Waiting 92 seconds for hard-stopped worker leases before offline restore',flush=True)
                for _ in range(46):time.sleep(2)
                restored=subprocess.run([*command,'restore',str(snapshot),'--confirm-restore'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
                assert restored.returncode==0,restored.stderr
                import sqlite3
                with closing(sqlite3.connect(directory/'business'/'app.db')) as state:
                    assert state.execute('SELECT count(*) FROM rag_indexes').fetchone()[0]==0
                api=subprocess.Popen([sys.executable,'-m','uvicorn','tests.chroma_server_evaluation:create_app','--factory','--host','127.0.0.1','--port',str(ap),'--workers','2','--log-level','warning'],env=env,stdout=log,stderr=log)
                wait_url(base+'/health')
                with httpx.Client(base_url=base,headers={'Origin':'https://demo.example'},timeout=45,trust_env=False) as restored_client:
                    restored_client.post('/auth/login',json={'username':'server_b','password':'fictional-password-123'}).raise_for_status()
                    restored_client.headers['Cookie']='__Host-my_agent_session='+restored_client.cookies['__Host-my_agent_session']
                    assert '5' in restored_client.post('/chat',json={'message':'1+4=?','mode':'chat'}).raise_for_status().json()['answer']
                    final=ready(restored_client,db)
                    assert final['generation']!=rowb['generation']
                    assert search(restored_client,db).raise_for_status().json()['hits']
                results['sqlite_restore']='tokens revoked, index states cleared, source reindexed with new generation; calculator available'
            print(json.dumps(results,ensure_ascii=False,indent=2),flush=True)
            print('PASS shared Chroma real server + two API worker isolation/concurrency/delete/outage/restart')
        finally:
            stop(api);stop(chroma);log.flush()
            from shutil import copyfile
            evidence=Path('.demo-runtime')
            evidence.mkdir(exist_ok=True)
            copyfile(directory/'process.log',evidence/'chroma-server-process-last.log')
            log.close()


if __name__=='__main__':run()
