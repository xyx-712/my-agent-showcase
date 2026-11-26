"""Real Edge, built frontend and fake chat model; fictional user data only."""
import base64
from pathlib import Path
from tests import auth_browser_evaluation as harness


def scenario(b,directory,expire):
    b.wait("!!document.querySelector('.auth-panel')")
    b.click('进入新的访客会话')
    b.wait("document.querySelector('.account-box strong')?.textContent==='访客会话'")
    b.click('登录 / 注册');b.click('注册')
    b.fill('input[autocomplete=username]','memory_ui_user')
    b.fill('input[type=password]','fictional-password-123')
    b.click('注册并登录')
    b.wait("document.querySelector('.account-box strong')?.textContent==='memory_ui_user'")
    b.click('自由聊天')
    def send(text):
        b.wait("!document.querySelector('.composer textarea').disabled")
        b.fill('.composer textarea',text)
        b.js("document.querySelector('.composer').requestSubmit()")
        b.wait("!document.querySelector('.composer textarea').disabled && document.querySelector('.composer textarea').value===''")
    def panel():
        b.click('长期记忆')
        b.wait("!!document.querySelector('.memory-panel') && ![...document.querySelectorAll('.memory-panel button')].find(b=>b.textContent==='重新载入').disabled")
    send('我叫李四')
    panel()
    b.wait("document.querySelector('.memory-record')?.textContent.includes('李四')")
    b.js("document.querySelector('.memory-record').click()")
    b.wait("document.querySelector('[aria-label=记忆内容]')?.value==='李四'")
    assert b.js("document.querySelector('.memory-detail').textContent.includes('用户陈述') && document.querySelector('.memory-detail').textContent.includes('来源消息')")
    b.fill('[aria-label=记忆内容]','王五')
    b.click('保存修改')
    b.wait("document.querySelector('.memory-success')?.textContent.includes('保存') && document.querySelector('.memory-record').textContent.includes('王五')")
    b.js("document.querySelector('.memory-record').click()")
    b.wait("document.querySelector('.memory-detail')?.textContent.includes('v2')")
    assert b.js("document.querySelectorAll('.memory-version').length===2")
    # Another authenticated request updates the same revision before the UI saves.
    assert b.js("""(async()=>{const rows=await (await fetch('/memories')).json();const item=rows.items.find(r=>r.key==='name');
        return (await fetch('/memories/'+item.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:'王五',revision:item.revision})})).ok;})()""")
    b.fill('[aria-label=记忆内容]','尚未保存的更改')
    b.click('保存修改')
    b.wait("document.querySelector('.memory-error')?.textContent.includes('尚未保存')")
    assert b.js("document.querySelector('[aria-label=记忆内容]').value==='尚未保存的更改'")
    b.click('重新载入')
    b.wait("!document.querySelector('.memory-error') && !!document.querySelector('.memory-record') && !document.querySelector('.memory-record').disabled")
    b.js("document.querySelector('[aria-label=自动记忆]').click()")
    b.wait("document.querySelector('.memory-success')?.textContent.includes('暂停')")
    b.js('location.reload()')
    b.wait("!!document.querySelector('.account-box strong')")
    panel()
    assert b.js("!document.querySelector('[aria-label=自动记忆]').checked && document.querySelector('.memory-record').textContent.includes('王五')")
    b.js("document.querySelector('[aria-label=关闭记忆管理]').click()")
    send('我喜欢苹果')
    panel()
    assert b.js("document.querySelectorAll('.memory-record').length===1")
    b.js("document.querySelector('[aria-label=自动记忆]').click()")
    b.wait("document.querySelector('.memory-success')?.textContent.includes('开启')")
    b.js("document.querySelector('[aria-label=关闭记忆管理]').click()")
    send('我喜欢篮球')
    panel()
    b.wait("document.querySelectorAll('.memory-record').length===2")
    b.js("[...document.querySelectorAll('.memory-record')].find(e=>e.textContent.includes('姓名')).click()")
    b.wait("!!document.querySelector('[aria-label=记忆内容]')")
    b.js("document.querySelector('.memory-delete input').click()")
    b.click('删除记忆')
    b.wait("document.querySelector('.memory-success')?.textContent.includes('删除') && document.querySelectorAll('.memory-record').length===1")
    b.js("document.querySelector('.memory-filters input').click()")
    b.wait("document.querySelectorAll('.memory-record').length===2 && document.body.textContent.includes('已删除')")
    b.js("[...document.querySelectorAll('.memory-record')].find(e=>e.textContent.includes('姓名')).click()")
    b.wait("document.querySelector('[aria-label=记忆内容]')?.disabled")
    assert b.js("document.body.textContent.includes('删除长期记忆不等于删除原始聊天记录和备份')")
    outputs=Path(__file__).resolve().parents[1]/'.demo-runtime'/'memory-management-ui'
    outputs.mkdir(parents=True,exist_ok=True)
    for name,width,height in [('desktop',1280,900),('narrow',390,844)]:
        b.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<700})
        assert b.js("document.documentElement.scrollWidth<=window.innerWidth && document.querySelector('.memory-panel').getBoundingClientRect().right<=window.innerWidth")
        (outputs/f'{name}.png').write_bytes(base64.b64decode(b.call('Page.captureScreenshot',{'format':'png'})['data']))
    b.call('Emulation.clearDeviceMetricsOverride')
    b.js("document.querySelector('[aria-label=关闭记忆管理]').click()")
    # Delay an old identity's response even after fetch returns, to exercise result rejection.
    b.js("""window.originalFetch=window.fetch;window.delayedMemory=false;
        window.fetch=async (...args)=>{const result=await window.originalFetch(...args);
          if(typeof args[0]==='string' && args[0].startsWith('/memories?')) {
            window.delayedMemory=true;await new Promise(resolve=>window.releaseMemory=resolve);
          }return result;};""")
    b.click('长期记忆');b.wait('window.delayedMemory')
    b.click('退出账号');b.wait("!!document.querySelector('.auth-panel')")
    b.click('进入新的访客会话')
    b.wait("document.querySelector('.account-box strong')?.textContent==='访客会话'")
    b.js('window.fetch=window.originalFetch;window.releaseMemory()')
    panel()
    assert b.js("document.querySelectorAll('.memory-record').length===0 && document.querySelector('[aria-label=自动记忆]').checked")
    b.js("document.querySelector('[aria-label=关闭记忆管理]').click()")
    b.fill('.composer textarea','未发送的草稿')
    panel();expire();b.click('重新载入')
    b.wait("!!document.querySelector('.auth-panel') && !document.querySelector('.memory-panel')")
    assert b.js("document.querySelector('.composer textarea').value==='未发送的草稿' && document.body.textContent.includes('会话已过期')")
    print('PASS Edge memory list/source/edit/revisions/delete/toggle/refresh, desktop+narrow, stale identity response and expired auth draft protection')


if __name__=='__main__':
    harness.scenario=scenario
    harness.run()
