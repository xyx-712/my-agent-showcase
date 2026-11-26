"""Reuse the isolated two-process harness; verify management CAS at both workers."""
from concurrent.futures import ThreadPoolExecutor
from tests.memory_workers_evaluation import run


def management(a,b):
    a.post('/chat',json={'message':'我叫李四','mode':'chat'}).raise_for_status()
    row=next(r for r in a.get('/memories').raise_for_status().json()['items'] if r['key']=='name')
    path=f"/memories/{row['id']}"
    assert a.get('/memories/settings').json()['automatic_enabled']
    def race(method,payloads):
        with ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(client.request,method,path,json=data) for client,data in zip((a,b),payloads)]
            results=[f.result() for f in futures]
        assert sorted(r.status_code for r in results)==[200,409],[(r.status_code,r.text) for r in results]
        assert len({r.headers['X-Test-Worker'] for r in results})==2
        return results
    race('PATCH',[{'value':'王五','revision':row['revision']},{'value':'赵六','revision':row['revision']}])
    updated=b.get(path).raise_for_status().json()
    assert updated['item']['revision']==row['revision']+1 and len(updated['versions'])==2
    version=updated['item']['revision']
    race('DELETE',[{'revision':version},{'revision':version}])
    assert a.get(path).json()['item']['status']=='deleted'
    assert b.patch(path,json={'value':'旧回放','revision':version}).status_code==409
    setting=a.get('/memories/settings').json()
    a.patch('/memories/settings',json={'automatic_enabled':False,'revision':setting['revision']}).raise_for_status()
    assert not b.get('/memories/settings').json()['automatic_enabled']
    b.post('/chat',json={'message':'我的职业是医生','mode':'chat'}).raise_for_status()
    assert not any(r['key']=='job' for r in a.get('/memories').json()['items'])
    setting=b.get('/memories/settings').json()
    b.patch('/memories/settings',json={'automatic_enabled':True,'revision':setting['revision']}).raise_for_status()
    a.post('/chat',json={'message':'我的职业是教师','mode':'chat'}).raise_for_status()
    assert any(r['key']=='job' and r['value']=='教师' for r in b.get('/memories').json()['items'])
    print('PASS distinct real worker management edit/delete CAS (200/409), immutable revisions, pause/resume and cross-worker visibility')


if __name__=='__main__':run(management)
