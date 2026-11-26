"""Built frontend unchanged: long history, summary use, refresh and account switch."""
import os
from tests import auth_browser_evaluation as harness
from tests.history_summary_evaluation import Model


model=Model()


def scenario(b,directory,expire):
    b.wait("!!document.querySelector('.auth-panel')")
    b.click('进入新的访客会话')
    b.wait("document.querySelector('.account-box strong')?.textContent==='访客会话'")
    from src.server.session import app_db
    from src.server.history import save_history
    with app_db() as db:user=db.execute('SELECT user_id FROM sessions').fetchone()[0]
    for text in ('项目青禾禁止删除文件','项目决定只在本地运行','较近的问候','最近闲聊'):
        save_history(user,'user',text);save_history(user,'assistant','已收到')
    b.js('location.reload()')
    b.wait("document.querySelector('.messages')?.textContent.includes('项目青禾禁止删除文件') && !document.querySelector('.composer textarea').disabled")
    b.click('自由聊天');b.fill('.composer textarea','项目早期要求是什么？')
    b.js("document.querySelector('.composer').requestSubmit()")
    b.wait("document.querySelector('.messages').textContent.includes('普通聊天回复') && !document.querySelector('.composer textarea').disabled")
    assert any('较早对话摘要' in m.content and '禁止删除文件' in m.content for m in model.answers[-1])
    with app_db() as db:
        state=db.execute('SELECT status,revision,end_id FROM history_summaries WHERE user_id=?',(user,)).fetchone()
        count=db.execute('SELECT count(*) FROM chat_messages WHERE user_id=?',(user,)).fetchone()[0]
    assert state==('READY',1,4) and count==10
    b.js('location.reload()')
    b.wait("document.querySelector('.messages')?.textContent.includes('项目早期要求是什么？')")
    b.click('长期记忆')
    b.wait("!!document.querySelector('.memory-panel')")
    assert b.js("document.querySelector('.memory-record')===null")
    b.js("document.querySelector('[aria-label=关闭记忆管理]').click()")
    b.click('结束访客会话')
    b.wait("!!document.querySelector('.auth-panel')")
    b.click('进入新的访客会话')
    b.wait("document.querySelector('.messages') && !document.querySelector('.messages').textContent.includes('青禾')")
    print('PASS Edge long-history original rows/summary-assisted prompt/refresh, memory distinction and guest switch')


if __name__=='__main__':
    os.environ.update(MY_AGENT_RAG_ENABLED='0',MY_AGENT_CONTEXT_TURNS='2',MY_AGENT_SUMMARY_MIN_TURNS='2',MY_AGENT_SUMMARY_BATCH_TURNS='2')
    harness.scenario=scenario;harness.run(model)
