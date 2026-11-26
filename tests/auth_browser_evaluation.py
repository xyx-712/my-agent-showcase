"""Headless Edge UI acceptance using CDP. Optional test dependency: websockets."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
from threading import Thread
import time
from urllib.request import urlopen

import uvicorn
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from websockets.sync.client import connect


class Browser:
    def __init__(self, websocket):
        self.ws = websocket
        self.sequence = 0

    def call(self, method, params=None):
        self.sequence += 1
        identity = self.sequence
        self.ws.send(json.dumps({"id": identity, "method": method, "params": params or {}}))
        while True:
            result = json.loads(self.ws.recv(timeout=15))
            if result.get("id") == identity:
                if "error" in result:
                    raise AssertionError(result)
                return result.get("result", {})

    def js(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in result:
            raise AssertionError(result)
        return result.get("result", {}).get("value")

    def wait(self, expression):
        for _ in range(100):
            if self.js(expression):
                return
            time.sleep(.1)
        raise AssertionError("UI condition timed out: " + expression + "\nPAGE: " + str(self.js("document.body.innerText"))[:1800])

    def click(self, text):
        self.wait("[...document.querySelectorAll('button')].some(b=>b.textContent.trim()===" + json.dumps(text) + " && !b.disabled)")
        self.js("(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==="
                + json.dumps(text) + ");if(!b)throw Error('button missing');b.click();})()")

    def fill(self, selector, value):
        self.js("(()=>{const e=document.querySelector(" + json.dumps(selector) + ");"
                "Object.getOwnPropertyDescriptor(e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(e,"
                + json.dumps(value) + ");e.dispatchEvent(new Event('input',{bubbles:true}));})()")


def scenario(browser, directory, expire):
    b = browser
    b.wait("!!document.querySelector('.auth-panel') && [...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='进入新的访客会话' && !b.disabled)")
    b.click("进入新的访客会话")
    b.wait("document.querySelector('.account-box strong').textContent==='访客会话'")
    assert b.js("!document.querySelector('.calendar-panel') && !document.querySelector('.demo-button') && !document.body.textContent.includes('加载演示资料')")
    b.click("登录 / 注册")
    b.click("注册")
    b.fill('input[autocomplete=username]', "ui_user")
    b.fill('input[type=password]', "ui-demo-password-123")
    b.js("document.querySelector('.auth-panel input[type=checkbox]').click()")
    b.click("注册并登录")
    b.wait("document.querySelector('.account-box strong').textContent==='ui_user'")

    fixture = directory / "fiction-ui.txt"
    fixture.write_text("Fictional UI evidence", encoding="utf-8")
    root = b.call("DOM.getDocument")["root"]["nodeId"]
    node = b.call("DOM.querySelector", {"nodeId": root, "selector": "input[type=file]"})["nodeId"]
    b.call("DOM.setFileInputFiles", {"nodeId": node, "files": [str(fixture)]})
    b.wait("!!document.querySelector('.file-name')")
    b.wait("!document.querySelector('textarea').disabled")
    from src.server.session import app_db
    with app_db() as db:
        db.execute("UPDATE rag_indexes SET status='FAILED',failure_reason='虚构索引失败' WHERE document_id IN (SELECT id FROM documents WHERE name='fiction-ui.txt')")
    b.wait("document.body.textContent.includes('索引失败')")
    b.click("重试索引")
    b.wait("document.body.textContent.includes('等待索引') && !document.querySelector('textarea').disabled")
    assert b.js("document.querySelector('input[type=file]').accept.includes('.docx')")
    from tests.test_retrieval_documents import docx_bytes
    word_fixture = directory / "fiction-ui.docx"
    word_fixture.write_bytes(docx_bytes())
    b.call("DOM.setFileInputFiles", {"nodeId": node, "files": [str(word_fixture)]})
    b.wait("document.querySelectorAll('.file-name').length===2 && !document.querySelector('textarea').disabled")
    b.js("document.querySelector('.file-name[title=\"fiction-ui.docx\"]').click()")
    b.wait("!!document.querySelector('.source-panel')")
    assert b.js("document.querySelector('.source-panel').textContent.includes('段落1') && document.querySelector('.source-panel').textContent.includes('表格1 行1 列2')")
    b.js("document.querySelector('[aria-label=\"关闭原文\"]').click()")
    b.js("document.querySelector('[aria-label=\"删除 fiction-ui.docx\"]').click()")
    b.wait("document.querySelectorAll('.file-name').length===1 && !document.querySelector('textarea').disabled")
    b.click("自由聊天")
    b.fill("textarea", "你好")
    b.js("document.querySelector('.composer').requestSubmit()")
    b.wait("document.querySelector('.messages').textContent.includes('本地浏览器离线回复')")
    b.click("退出账号")
    b.wait("!!document.querySelector('.auth-panel')")
    b.click("登录")
    b.fill('input[autocomplete=username]', "ui_user")
    b.fill('input[type=password]', "ui-demo-password-123")
    b.click("登录")
    # Tab and submit have the same label, so explicitly submit the form.
    b.js("document.querySelector('.auth-panel form').requestSubmit()")
    b.wait("document.querySelector('.account-box strong').textContent==='ui_user'")
    b.wait("!!document.querySelector('.file-name') && document.querySelector('.messages').textContent.includes('本地浏览器离线回复')")
    b.js("location.reload()")
    b.wait("document.querySelector('.account-box strong')?.textContent==='ui_user'")
    b.wait("!!document.querySelector('.file-name')")

    b.js("""window.originalFetch=window.fetch; window.delayed=false;
        window.fetch=async (...args)=>{
          const response=await window.originalFetch(...args);
          if(typeof args[0]==='string' && /^\/documents\/[a-f0-9]+$/.test(args[0])) {
            window.delayed=true;
            await new Promise(resolve=>window.releaseSource=resolve);
          }
          return response;
        };""")
    b.js("document.querySelector('.file-name').click()")
    b.wait("window.delayed")
    b.click("退出账号")
    b.wait("!!document.querySelector('.auth-panel')")
    b.click("注册")
    b.fill('input[autocomplete=username]', "ui_second")
    b.fill('input[type=password]', "ui-demo-password-456")
    b.click("注册并登录")
    b.wait("document.querySelector('.account-box strong').textContent==='ui_second'")
    b.js("window.releaseSource()")
    time.sleep(.3)
    assert b.js("!document.querySelector('.file-name') && !document.querySelector('.source-panel') && !document.querySelector('.messages').textContent.includes('本地浏览器离线回复')")
    b.click("账号管理")
    b.wait("document.body.textContent.includes('登录设备')")
    b.wait("!!document.querySelector('.session-row')")
    b.js("[...document.querySelectorAll('.auth-panel button')].find(e=>e.textContent==='关闭').click()")
    b.click("＋ 新任务")
    b.wait("!!document.querySelector('.task-list button')")
    b.call("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    assert b.js("document.documentElement.scrollWidth<=window.innerWidth")
    b.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
    assert b.js("document.documentElement.scrollWidth<=window.innerWidth")
    b.call("Emulation.clearDeviceMetricsOverride")
    b.fill("textarea", "尚未发送的草稿")
    expire()
    b.js("document.querySelector('.composer').requestSubmit()")
    b.wait("!!document.querySelector('.auth-panel')")
    assert b.js("document.querySelector('textarea').value==='尚未发送的草稿'")
    assert b.js("document.body.textContent.includes('会话已过期')")
    b.click("登录")
    b.fill('input[autocomplete=username]', "ui_second")
    b.fill('input[type=password]', "ui-demo-password-456")
    b.js("document.querySelector('.auth-panel form').requestSubmit()")
    b.wait("document.querySelector('.account-box strong').textContent==='ui_second'")
    assert b.js("document.querySelector('textarea').value==='尚未发送的草稿'")
    print("PASS Edge UI register, upload, chat, logout, login, refresh and delayed A response after switch to B")


def browser_executable():
    """Resolve an explicit test browser or PATH, without fixed install locations."""
    import os
    import shutil
    from pathlib import Path
    configured = os.environ.get("MY_AGENT_TEST_BROWSER", "")
    candidate = (shutil.which(configured) or configured) if configured else (shutil.which("msedge") or shutil.which("msedge.exe"))
    if not candidate or not Path(candidate).expanduser().is_file():
        raise FileNotFoundError("Browser unavailable: set MY_AGENT_TEST_BROWSER to an existing executable or add msedge to PATH")
    return str(Path(candidate).expanduser().resolve())


def run(model=None):
    executable = browser_executable()
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        from src import config
        for field in ("APP_DB", "MEMORY_DB", "CHECKPOINT_DB"):
            setattr(config, field, directory / (field + ".db"))
        from src.server import history
        history.HISTORY_FILE = directory / "history.json"
        from src.server import api
        class Model:
            def invoke(self, messages):
                if "规划普通聊天任务" in messages[0].content:
                    return AIMessage(content='{"action":"chat","steps":[],"question":""}')
                return AIMessage(content="本地浏览器离线回复")
        api.general_agent.llm = model or Model()
        api.app.mount("/", StaticFiles(directory=config.PROJECT_DIR / "frontend" / "dist", html=True))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        url = "http://127.0.0.1:" + str(sock.getsockname()[1])
        api.allowed_origins.add(url)
        server = uvicorn.Server(uvicorn.Config(api.app, log_level="warning"))
        thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        browser_process = None
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            profile = directory / "edge-profile"
            browser_process = subprocess.Popen([
                executable,
                "--headless=new", "--remote-debugging-port=0", "--no-first-run",
                "--no-default-browser-check", "--user-data-dir=" + str(profile), url,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            port_file = profile / "DevToolsActivePort"
            for _ in range(200):
                if port_file.exists():
                    break
                time.sleep(.1)
            port = int(port_file.read_text().splitlines()[0])
            with urlopen(f"http://127.0.0.1:{port}/json/list") as response:
                targets = json.load(response)
            target = next(t for t in targets if t["type"] == "page" and t["url"].startswith(url))
            with connect(target["webSocketDebuggerUrl"]) as websocket:
                def expire():
                    from src.server.session import app_db
                    with app_db() as db:
                        db.execute("UPDATE sessions SET expires_at=0")
                scenario(Browser(websocket), directory, expire)
                Browser(websocket).call("Browser.close")
            browser_process.wait(timeout=10)
        finally:
            if browser_process and browser_process.poll() is None:
                browser_process.terminate()
                browser_process.wait(timeout=10)
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
            api.general_agent.conn.close()
            import os
            if os.environ.get('MY_AGENT_RAG_ENABLED') == '1':
                from tests.vector_index_evaluation import close_test_chroma
                close_test_chroma()


if __name__ == "__main__":
    run()
