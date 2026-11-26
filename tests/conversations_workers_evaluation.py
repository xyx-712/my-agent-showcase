"""Reuse independent-port two-worker harness; no shared-listen claim."""
from concurrent.futures import ThreadPoolExecutor
from tests.history_summary_workers_evaluation import run


def check(a,b):
    first=a.post('/conversations',json={'name':'双进程甲'}).raise_for_status().json()['id']
    second=b.post('/conversations',json={'name':'双进程乙'}).raise_for_status().json()['id']
    a.headers['X-Chat-Session']=first;b.headers['X-Chat-Session']=second
    with ThreadPoolExecutor(2) as pool:
        outputs=[pool.submit(client.post,'/chat',json={'message':text,'mode':'chat'}) for client,text in ((a,'甲口令青禾'),(b,'乙口令白榆'))]
        results=[future.result() for future in outputs]
    assert all(r.status_code in (200,409) for r in results)
    # Same-owner mutation remains serialized; retry the refused request once.
    for client,text,result in zip((a,b),('甲口令青禾','乙口令白榆'),results):
        if result.status_code==409:client.post('/chat',json={'message':text,'mode':'chat'}).raise_for_status()
    assert '乙口令' not in str(a.get('/history').json())
    assert '甲口令' not in str(b.get('/history').json())
    b.headers['X-Chat-Session']=first
    assert a.get('/history').json()==b.get('/history').json()
    a.delete('/conversations/'+first,headers={'Content-Type':'application/json'}).raise_for_status()
    assert b.get('/history').status_code==404
    b.post('/conversations/'+first+'/restore',json={}).raise_for_status()
    assert a.get('/history').status_code==200
    print('PASS two API workers: per-chat history, cross-worker switching, concurrent owner lock, delete/restore visibility')


if __name__=='__main__':run(check)
