"""Real Edge UI: independent chats, shared memory, soft delete and stale responses."""
import base64
from pathlib import Path
from tests import auth_browser_evaluation as harness
from tests.history_summary_evaluation import Model


model=Model()


def scenario(b,directory,expire):
    b.wait("!!document.querySelector('.auth-panel')")
    b.click('进入新的访客会话')
    b.wait("!!document.querySelector('.conversations-panel') && !document.querySelector('.composer textarea').disabled")
    def ready():b.wait("!document.querySelector('.composer textarea').disabled && ![...document.querySelectorAll('button')].find(e=>e.textContent==='新建聊天').disabled")
    def new(name):
        b.fill('[aria-label=新会话名称]',name);b.click('新建聊天')
        b.wait("document.querySelector('.active-conversation')?.textContent==="+repr(name));ready()
    def choose(name):
        b.click(name);b.wait("document.querySelector('.active-conversation')?.textContent==="+repr(name));ready()
    def send(text):
        ready();b.fill('.composer textarea',text);b.js("document.querySelector('.composer').requestSubmit()")
        b.wait("document.querySelector('.composer textarea').value==='' && !document.querySelector('.composer textarea').disabled")
    new('浏览器甲');send('我叫李四');send('甲独有信息青禾')
    fixture=directory/'fictional-chat.txt';fixture.write_text('虚构的甲会话文档',encoding='utf-8')
    root=b.call('DOM.getDocument')['root']['nodeId']
    node=b.call('DOM.querySelector',{'nodeId':root,'selector':'input[type=file]'})['nodeId']
    b.call('DOM.setFileInputFiles',{'nodeId':node,'files':[str(fixture)]})
    b.wait("!!document.querySelector('.file-name')");ready()
    new('浏览器乙')
    assert b.js("!document.querySelector('.file-name') && !document.querySelector('.messages').textContent.includes('甲独有')")
    send('我的名字是什么')
    assert 'name: 李四' in model.answers[-1][0].content
    b.click('长期记忆');b.wait("document.querySelector('.memory-record')?.textContent.includes('李四')")
    b.js("document.querySelector('[aria-label=关闭记忆管理]').click()")
    choose('浏览器甲')
    b.js("""window.originalFetch=window.fetch;window.delayedChatSource=false;
        window.fetch=async (...args)=>{const response=await window.originalFetch(...args);
        if(typeof args[0]==='string' && /^\/documents\/[a-f0-9]+$/.test(args[0])) {
            window.delayedChatSource=true;await new Promise(resolve=>window.releaseChatSource=resolve);
        } return response;};""")
    b.js("document.querySelector('.file-name').click()")
    b.wait('window.delayedChatSource');choose('浏览器乙')
    b.js('window.fetch=window.originalFetch;window.releaseChatSource()')
    assert b.js("!document.querySelector('.source-panel') && !document.querySelector('.file-name')")
    choose('浏览器甲')
    b.js("document.querySelector('[aria-label=\"删除会话 浏览器甲\"]').click()")
    b.wait("document.querySelector('.active-conversation')?.textContent==='默认会话'");ready()
    b.js("document.querySelector('.conversations-panel > label input').click()")
    b.wait("!!document.querySelector('[aria-label=\"恢复会话 浏览器甲\"]')")
    b.js("document.querySelector('[aria-label=\"恢复会话 浏览器甲\"]').click()")
    b.wait("document.querySelector('.active-conversation')?.textContent==='浏览器甲'");ready()
    assert b.js("!!document.querySelector('.file-name') && document.querySelector('.messages').textContent.includes('甲独有信息')")
    b.js('location.reload()')
    b.wait("document.querySelector('.active-conversation')?.textContent==='浏览器甲' && !!document.querySelector('.file-name')")
    outputs=Path(__file__).resolve().parents[1]/'.demo-runtime'/'conversations-ui';outputs.mkdir(parents=True,exist_ok=True)
    for name,width,height in [('desktop',1280,900),('narrow',390,844)]:
        b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<700})
        assert b.js('document.documentElement.scrollWidth<=window.innerWidth')
        assert b.js("document.querySelector('.header').getBoundingClientRect().top>=0 && document.querySelector('.brand').getBoundingClientRect().top>=0")
        (outputs/f'{name}.png').write_bytes(base64.b64decode(b.call('Page.captureScreenshot',{'format':'png'})['data']))
    b.call('Emulation.clearDeviceMetricsOverride')
    b.click('结束访客会话');b.wait("!!document.querySelector('.auth-panel')")
    b.click('进入新的访客会话');ready()
    assert b.js("document.querySelectorAll('.conversation-list > div').length===1 && !document.querySelector('.file-name') && !document.querySelector('.messages').textContent.includes('甲独有')")
    print('PASS Edge conversation create/switch/shared memory/files/soft delete/restore/refresh/stale response/identity switch and desktop+narrow')


if __name__=='__main__':
    import os
    os.environ['MY_AGENT_RAG_ENABLED']='0'
    harness.scenario=scenario;harness.run(model)
