"""Existing production UI, real Ollama RAG, isolated headless Edge profile."""
import os
import time
from tests import auth_browser_evaluation as ui


def scenario(b, directory, expire):
    def wait(expression):
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if b.js(expression): return
            time.sleep(.2)
        raise AssertionError('RAG UI timeout: '+str(b.js('document.body.innerText')))
    b.wait=wait
    b.click('进入新的访客会话')
    wait("document.querySelector('.account-box strong')?.textContent==='访客会话'")
    from tests.abstract_evaluation import pdf
    from docx import Document
    path=directory/'library.pdf'
    path.write_bytes(pdf(['Library opening hours: Monday to Friday, 9 AM to 6 PM.']))
    doc=Document();doc.add_paragraph('青禾食堂的午餐供应时间是每天十二点到十三点。')
    table=doc.add_table(rows=1,cols=1);table.cell(0,0).text='青禾食堂的午餐价格为每份二十元。'
    doc.save(directory/'canteen.docx')
    root=b.call('DOM.getDocument')['root']['nodeId']
    node=b.call('DOM.querySelector',{'nodeId':root,'selector':'input[type=file]'})['nodeId']
    b.call('DOM.setFileInputFiles',{'nodeId':node,'files':[str(path),str(directory/'canteen.docx')]})
    wait("document.querySelectorAll('.file-name').length===2 && [...document.querySelectorAll('.file-name')].every(e=>e.textContent.includes('可检索'))")
    if '--auto' not in __import__('sys').argv:
        b.click('文件问答')
    for question, label, expected in [('What are the library opening hours?','library.pdf','第 1 页'),
                                      ('青禾食堂午餐供应时间是什么？','canteen.docx','段落1'),
                                      ('青禾食堂午餐每份价格是多少？','canteen.docx','表格1 行1 列1')]:
        if '--auto' in __import__('sys').argv:
            question = '根据上传的文件 ' + label + '，' + question
        before=b.js("document.querySelectorAll('.message-row.assistant').length")
        b.fill('textarea',question)
        b.js("document.querySelector('.composer').requestSubmit()")
        wait(f"document.querySelectorAll('.message-row.assistant').length>{before} && !document.querySelector('textarea').disabled")
        wait("[...document.querySelectorAll('.citation')].some(e=>e.textContent.includes("+repr(label)+") && e.textContent.includes("+repr(expected)+"))")
        b.js("[...document.querySelectorAll('.citation')].filter(e=>e.textContent.includes("+repr(label)+") && e.textContent.includes("+repr(expected)+")).at(-1).click()")
        wait("!!document.querySelector('.source-panel')")
        assert b.js("document.querySelector('.source-panel').textContent.includes("+repr(expected.replace('第 1 页','第 1 页'))+")")
        b.js("document.querySelector('[aria-label=\"关闭原文\"]').click()")
    print('PASS real Edge upload -> READY -> PDF/DOCX questions -> cited answers -> source panel page/paragraph/table')


if __name__=='__main__':
    os.environ['MY_AGENT_RAG_ENABLED']='1'
    os.environ['MY_AGENT_EMBEDDING_MODEL']='embeddinggemma'
    os.environ.pop('MY_AGENT_CHROMA_DIR',None)
    os.environ.pop('MY_AGENT_CHROMA_URL',None)
    # Model provider reads configuration but does not open databases; ui.run binds
    # temporary database paths before importing the API/session modules.
    from src.agent.model_provider import get_chat_model
    ui.scenario=scenario
    ui.run(get_chat_model())
