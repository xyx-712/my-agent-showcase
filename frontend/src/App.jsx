import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import AccountPanel from './AccountPanel'
import MemoryPanel from './MemoryPanel'

import { request } from './request.js'

function docxPosition(chunk) {
  return `${chunk.table ? `表格${chunk.table} 行${chunk.row} 列${chunk.column}` : `段落${chunk.paragraph}`} · 字符${chunk.offset_start}–${chunk.offset_end}`
}

const jsonPost = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

function App() {
  const selectedChat = useRef(null)
  const [conversations, setConversations] = useState([])
  const [chatId, setChatId] = useState(null)
  const [showDeletedChats, setShowDeletedChats] = useState(false)
  const [chatName, setChatName] = useState('')
  const api = useCallback((path, options = {}) => request(path, { ...options,
    headers: { ...(selectedChat.current ? { 'X-Chat-Session': selectedChat.current } : {}), ...options.headers } }), [])
  const epoch = useRef(0)
  const lastRequest = useRef(null)
  const expiredDraft = useRef(null)
  const [identity, setIdentity] = useState({ kind: 'anonymous' })
  const [accountOpen, setAccountOpen] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [memoryGeneration, setMemoryGeneration] = useState(0)
  const [authOpen, setAuthOpen] = useState(false)
  const [authTab, setAuthTab] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [keepGuest, setKeepGuest] = useState(false)
  const bottom = useRef(null)
  const [mode, setMode] = useState('auto')
  const [messages, setMessages] = useState([])
  const [files, setFiles] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(true)
  const [status, setStatus] = useState('正在加载')
  const [task, setTask] = useState({})
  const [tasks, setTasks] = useState([])
  const [source, setSource] = useState(null)

  useEffect(() => {
    if (identity.kind === 'anonymous') return
    let disposed = false
    const timer = setInterval(async () => {
      const generation = epoch.current
      const scope = selectedChat.current
      try {
        const data = await api('/documents')
        if (!disposed && generation === epoch.current && scope === selectedChat.current) setFiles(data.files)
      } catch { /* Existing interactive requests handle expired identity and drafts. */ }
    }, 3000)
    return () => { disposed = true; clearInterval(timer) }
  }, [identity.kind, identity.username, api])

  useEffect(() => {
    const container = bottom.current?.closest('.chat-container')
    container?.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }, [messages, status])

  function clearIdentityData(preserveDraft = false) {
    selectedChat.current = null
    sessionStorage.removeItem('my-agent-chat-session')
    setChatId(null)
    setConversations([])
    if (!preserveDraft) setInput('')
    lastRequest.current = null
    setMessages([])
    setFiles([])
    setTask({})
    setTasks([])
    setSource(null)
    setAccountOpen(false)
    setMemoryOpen(false)
    setMode('auto')
  }

  function report(error, generation) {
    if (generation !== epoch.current) return
    if (error.status === 401) {
      expiredDraft.current = { text: input, username: identity.username }
      epoch.current++
      clearIdentityData(true)
      setIdentity({ kind: 'anonymous' })
      setAuthOpen(true)
      setBusy(false)
      setStatus('会话已过期。输入草稿已保留，请登录或进入新访客会话。')
    } else setStatus(error.message)
  }

  const refresh = useCallback(async (generation) => {
    const list = await api('/conversations')
    if (generation !== epoch.current) return
    const preferred = selectedChat.current || sessionStorage.getItem('my-agent-chat-session')
    const chosen = list.sessions.find(row => row.id === preferred && !row.deleted) || list.sessions.find(row => row.is_default)
    selectedChat.current = chosen.id
    sessionStorage.setItem('my-agent-chat-session', chosen.id)
    setChatId(chosen.id)
    setConversations(list.sessions)
    const [attachments, current, history, taskList] = await Promise.all([api('/documents'), api('/task'), api('/history'), api('/tasks')])
    if (generation !== epoch.current) return
    setFiles(attachments.files)
    setTask(current)
    setTasks(taskList.tasks)
    setMessages(history.messages)
  }, [api])

  async function switchChat(identity) {
    const generation = ++epoch.current
    selectedChat.current = identity
    sessionStorage.setItem('my-agent-chat-session', identity)
    setChatId(identity)
    setMessages([]); setFiles([]); setTasks([]); setTask({}); setSource(null)
    setMemoryOpen(false); setInput(''); lastRequest.current = null
    setBusy(true); setStatus('正在切换聊天…')
    try { await refresh(generation); if (generation === epoch.current) setStatus('') }
    catch (error) { report(error, generation) }
    finally { if (generation === epoch.current) setBusy(false) }
  }

  async function manageChat(action) {
    const generation = epoch.current
    setBusy(true)
    try {
      const result = await action()
      if (generation !== epoch.current) return
      setChatName('')
      if (result.id && !result.deleted) await switchChat(result.id)
      else if (result.deleted && result.id === selectedChat.current) await switchChat(conversations.find(row => row.is_default).id)
      else await refresh(generation)
    } catch (error) { report(error, generation) }
    finally { if (generation === epoch.current) setBusy(false) }
  }

  useEffect(() => {
    const generation = ++epoch.current
    async function initialize() {
      try {
        const current = await api('/auth/me')
        if (generation !== epoch.current) return
        setIdentity(current)
        if (current.kind !== 'anonymous') await refresh(generation)
        if (generation === epoch.current) setStatus('')
      } catch (error) {
        if (generation === epoch.current) {
          setStatus(error.message)
          if (error.status === 401) {
            clearIdentityData()
            setIdentity({ kind: 'anonymous' })
          }
        }
      } finally { if (generation === epoch.current) setBusy(false) }
    }
    initialize()
    return () => { if (epoch.current === generation) epoch.current = generation + 1 }
  }, [api, refresh])

  async function changeIdentity(action) {
    const generation = ++epoch.current
    clearIdentityData()
    setBusy(true)
    setStatus('')
    try {
      const current = await action()
      if (generation !== epoch.current) return
      setIdentity(current)
      if (current.kind === 'account' && expiredDraft.current?.username === current.username) {
        setInput(expiredDraft.current.text)
      }
      expiredDraft.current = null
      setPassword('')
      setAuthOpen(false)
      if (current.kind !== 'anonymous') await refresh(generation)
    } catch (error) {
      if (generation !== epoch.current) return
      setStatus(error.message)
      try {
        const current = await api('/auth/me')
        if (generation !== epoch.current) return
        setIdentity(current)
        if (current.kind !== 'anonymous') await refresh(generation)
      } catch (recoveryError) {
        if (generation === epoch.current) setStatus(recoveryError.message)
      }
    } finally { if (generation === epoch.current) setBusy(false) }
  }

  function submitAuth(event) {
    event.preventDefault()
    changeIdentity(() => api('/auth/' + authTab, jsonPost({
      username, password, ...(authTab === 'register' ? { keep_guest_data: keepGuest } : {}),
    })))
  }

  async function guest() {
    await changeIdentity(async () => {
      await api('/session', jsonPost({}))
      return api('/auth/me')
    })
  }

  async function upload(event) {
    const selected = [...event.target.files]
    event.target.value = ''
    const generation = epoch.current
    setBusy(true)
    const outcomes = []
    try {
      for (const file of selected) {
        if (generation !== epoch.current) return
        setStatus(`正在上传并解析 ${file.name}`)
        const body = new FormData()
        body.append('file', file)
        try {
          await api('/documents', { method: 'POST', body })
          outcomes.push(`${file.name} 解析完成`)
        } catch (error) {
          if (error.status === 401) throw error
          outcomes.push(`${file.name}：${error.message}`)
        }
      }
      await refresh(generation)
      if (generation === epoch.current) setStatus(outcomes.join('；'))
    } catch (error) { report(error, generation) }
    finally { if (generation === epoch.current) setBusy(false) }
  }

  async function mutate(action) {
    const generation = epoch.current
    setBusy(true)
    try {
      await action()
      await refresh(generation)
      if (generation === epoch.current) setStatus('资料已更新')
    } catch (error) { report(error, generation) }
    finally { if (generation === epoch.current) setBusy(false) }
  }

  async function send(event) {
    event.preventDefault()
    const message = input.trim()
    if (!message || busy) return
    const generation = epoch.current
    setMessages(previous => [...previous, { role: 'user', content: message }])
    setBusy(true)
    setStatus('正在思考…')
    try {
      const fingerprint = JSON.stringify([message, mode, task.id])
      if (lastRequest.current?.fingerprint !== fingerprint) lastRequest.current = { fingerprint, id: crypto.randomUUID() }
      await api('/chat', jsonPost({ message, mode, task_id: task.id || null, request_id: lastRequest.current.id }))
      if (generation !== epoch.current) return
      setInput('')
      lastRequest.current = null
      await refresh(generation)
      if (generation === epoch.current) setStatus('')
    } catch (error) {
      report(error, generation)
      if (error.status === 409) {
        try { await refresh(generation) } catch (refreshError) { report(refreshError, generation) }
      }
    } finally { if (generation === epoch.current) setBusy(false) }
  }

  async function showSource(id) {
    const generation = epoch.current
    try {
      const document = await api(`/documents/${id}`)
      if (generation === epoch.current) setSource(document)
    } catch (error) { report(error, generation) }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">M</span><strong>My Agent</strong><span className="local-label">LOCAL</span></div>
        <div className="account-box">
          <strong>{identity.kind === 'account' ? identity.username : identity.kind === 'guest' ? '访客会话' : '尚未登录'}</strong>
          {identity.kind === 'account' && <button onClick={() => setAccountOpen(true)}>账号管理</button>}
          {identity.kind !== 'anonymous' && <button onClick={() => { setMemoryGeneration(epoch.current); setMemoryOpen(true) }}>长期记忆</button>}
          {identity.kind !== 'account' && <button onClick={() => { setStatus(''); setAuthOpen(true) }}>登录 / 注册</button>}
          {identity.kind !== 'anonymous' && <button onClick={() => changeIdentity(() => api('/auth/logout', jsonPost({})))}>
            {identity.kind === 'account' ? '退出账号' : '结束访客会话'}</button>}
        </div>
        {identity.kind !== 'anonymous' && <section className="conversations-panel" aria-label="聊天会话">
          <div className="sidebar-title"><h2>聊天会话</h2><span>{conversations.filter(row => !row.deleted).length}</span></div>
          <form onSubmit={event => { event.preventDefault(); manageChat(() => api('/conversations', jsonPost({ name: chatName.trim() || '新聊天' }))) }}>
            <input aria-label="新会话名称" value={chatName} maxLength={60} placeholder="新会话名称" disabled={busy} onChange={event => setChatName(event.target.value)} />
            <button disabled={busy}>新建聊天</button>
          </form>
          <div className="conversation-list">{conversations.filter(row => showDeletedChats || !row.deleted).map(row => <div key={row.id}>
            <button className={chatId === row.id ? 'active-conversation' : ''} disabled={busy || !!row.deleted} onClick={() => switchChat(row.id)}>{row.name}{row.deleted ? ' · 已删除' : ''}</button>
            <button disabled={busy || !!row.is_default} aria-label={`${row.deleted ? '恢复' : '删除'}会话 ${row.name}`}
              title={row.is_default ? '默认会话保留为兼容入口' : '软删除保留原始资料，可恢复'}
              onClick={() => manageChat(() => row.deleted ? api(`/conversations/${row.id}/restore`, jsonPost({})) : api(`/conversations/${row.id}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' } }))}>{row.deleted ? '恢复' : '删除'}</button>
          </div>)}</div>
          <label><input type="checkbox" checked={showDeletedChats} onChange={event => setShowDeletedChats(event.target.checked)} />显示已删除会话</label>
        </section>}
        <div className="sidebar-title"><h2>会话资料</h2><span>{files.length} 个文件</span></div>
        <label className={`upload-zone ${busy ? 'disabled' : ''}`}>
          <span className="upload-symbol">＋</span><strong>添加文件</strong>
          <small>TXT、Markdown、PDF、DOCX、Excel<br />每个文件最多 5 MiB</small>
          <input type="file" multiple accept=".txt,.md,.pdf,.xlsx,.docx" disabled={busy || identity.kind === 'anonymous'} onChange={upload} />
        </label>
        <section className="tasks-panel">
          <div className="sidebar-title"><h2>任务</h2><button disabled={busy} onClick={() => mutate(() => api('/tasks/new', jsonPost({ name: '新任务' })))}>＋ 新任务</button></div>
          <div className="task-list">{tasks.map(item => <button key={item.id} disabled={busy}
            className={task.id === item.id ? 'selected-task' : ''}
            onClick={() => mutate(() => api('/tasks/select', jsonPost({ id: item.id })))}>
              <strong>{item.name}</strong><small>{item.status} · {item.pending || '已完成'}</small>
          </button>)}</div>
          {task.id && <details><summary>当前任务执行记录</summary>
            <p>{task.request}</p><p>已检索 {task.result_summary?.sources || 0} 个片段{task.result_summary?.remaining != null ? ` · 剩余 ${task.result_summary.remaining} 个工作日` : ''}</p>{task.completed?.map((step, i) => <div key={i}>✓ {step}</div>)}
            <button disabled={busy} onClick={() => mutate(() => api('/tasks/pause', jsonPost({})))}>暂停任务</button>
          </details>}
        </section>
        <div className="file-list">
          {files.map(file => <div key={file.id} className="file-row">
            <span className="file-type">{file.name.split('.').pop().toUpperCase()}</span>
            <button className="file-name" onClick={() => showSource(file.id)} title={file.name}>{file.name}<small>已解析 · 点击查看</small><small>{({ PENDING: '等待索引', INDEXING: '正在索引', READY: '可检索', FAILED: '索引失败' })[file.index?.status] || '等待索引'}</small></button>
            <button className="reindex-file" title={file.index?.failure_reason || '重新建立向量索引'} disabled={busy || file.index?.status === 'INDEXING'}
              onClick={() => mutate(() => api(`/documents/${file.id}/reindex`, jsonPost({}))) }>{file.index?.status === 'FAILED' ? '重试索引' : '重新索引'}</button>
            {file.index?.failure_reason && <small className="index-error">{file.index.failure_reason}</small>}
            <button className="remove-file" aria-label={`删除 ${file.name}`} disabled={busy || identity.kind === 'anonymous'}
              onClick={() => mutate(() => api(`/documents/${file.id}`, { method: 'DELETE' }))}>×</button>
          </div>)}
          {!files.length && <p className="no-files">上传后，可随时查看回答的原文依据。</p>}
        </div>
        <div className="sidebar-foot"><span className="status-dot" />本机 Ollama<span>会话资料独立保存</span></div>
      </aside>
      <div className="workspace">
        <header className="header"><div><h1>对话</h1><p>自由聊天，也可以结合资料深入分析。</p></div><span className="header-tag">本地助手</span></header>
        <main className="chat-container"><div className="messages">
          {!messages.length && <div className="welcome">
            <div className="welcome-icon">M</div><h2>今天想聊些什么？</h2>
            <p>直接提问，或添加文件后一起分析。</p>
            <div className="suggestions">
              <button onClick={() => setInput('你好，请介绍一下你自己。')}>认识一下助手 <span>↗</span></button>
              <button onClick={() => setInput('总结这些文件中的主要变更，并标注依据。')}>整理文件变更 <span>↗</span></button>
            </div>
          </div>}
          {messages.map((message, index) => <div key={index} className={`message-row ${message.role}`}>
            {message.role === 'assistant' && <span className="assistant-mark">M</span>}
            <div className="message-body"><span className="message-author">{message.role === 'assistant' ? 'My Agent' : '你'}</span>
              <div className="message-bubble">{message.content}</div>
              {!!message.citations?.length && <div className="citations">{message.citations.map((citation, i) => <button className="citation" key={i}
                onClick={() => showSource(citation.file_id)}>↗ {citation.name}{citation.method === 'docx' ? ` · ${docxPosition(citation)}` : citation.sheet ? ` · ${citation.sheet}!${citation.range}` : `${citation.page ? ` · 第 ${citation.page} 页` : ''} · L${citation.start}–${citation.end}`}</button>)}</div>}
            </div>
          </div>)}
          <div ref={bottom} />
        </div></main>
        <footer className="input-area">
          <div className="task-status" role="status">{status || (task.pending ? '文件任务已暂停，可补充条件或继续任务。' : '')}
            {task.pending && <button disabled={busy || identity.kind === 'anonymous'} onClick={() => { setMode('documents'); setInput('继续任务') }}>继续任务 ↗</button>}
          </div>
          <form className="composer" onSubmit={send}>
            <textarea aria-label="消息" value={input} onChange={e => setInput(e.target.value)} disabled={busy || identity.kind === 'anonymous'}
              placeholder="输入消息，自由聊天或询问文件…" onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) send(e)
              }} />
            <div className="composer-bottom">
              <div className="mode-switch" aria-label="回答方式">
                {[['auto', '自动'], ['chat', '自由聊天'], ['documents', '文件问答']].map(([value, label]) =>
                  <button type="button" key={value} aria-pressed={mode === value} disabled={busy || identity.kind === 'anonymous'}
                    className={mode === value ? 'active' : ''} onClick={() => setMode(value)}>{label}</button>)}
              </div>
              <button className="send-button" aria-label="发送消息" disabled={busy || identity.kind === 'anonymous' || !input.trim()}>{busy ? '···' : '↑'}</button>
            </div>
          </form>
          <p className="composer-hint">{mode === 'chat' ? '自由聊天模式使用对话上下文，附件任务保留。' : mode === 'documents' ? '结合当前会话文件回答，并提供原文依据。' : '自动选择聊天、工具、知识库或文档分析 · Enter 发送，Shift + Enter 换行'}</p>
        </footer>
      </div>
      {(authOpen || identity.kind === 'anonymous') && <div className="source-overlay">
        <section className="auth-panel" role="dialog" aria-modal="true" aria-label="用户登录">
          <h2>{authTab === 'login' ? '欢迎回来' : '创建账号'}</h2>
          <p>登录后，可跨浏览器恢复自己的对话与资料。</p>
          <div className="auth-tabs">
            <button onClick={() => { setAuthTab('login'); setStatus('') }}>登录</button>
            <button onClick={() => { setAuthTab('register'); setStatus('') }}>注册</button>
          </div>
          <button className="guest-button" onClick={() => setAccountOpen(true)}>忘记密码？</button>
          <form onSubmit={submitAuth}>
            <label>用户名<input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)}
              required minLength={3} maxLength={32} placeholder="3–32 位字母、数字或下划线" /></label>
            <label>密码<input type="password" autoComplete={authTab === 'login' ? 'current-password' : 'new-password'}
              value={password} onChange={e => setPassword(e.target.value)} required minLength={10} maxLength={128} placeholder="10–128 个字符" /></label>
            {authTab === 'register' && identity.kind === 'guest' && <label className="keep-data">
              <input type="checkbox" checked={keepGuest} onChange={e => setKeepGuest(e.target.checked)} />保留本次访客资料与聊天</label>}
            <p role="alert">{status}</p>
            <button className="auth-submit" disabled={busy}>{busy ? '正在处理…' : authTab === 'login' ? '登录' : '注册并登录'}</button>
          </form>
          {identity.kind === 'anonymous' ? <button className="guest-button" disabled={busy} onClick={guest}>进入新的访客会话</button>
            : <button className="guest-button" onClick={() => { setAuthOpen(false); setPassword('') }}>返回当前会话</button>}
        </section>
      </div>}
      {accountOpen && <AccountPanel identity={identity} request={api} onClose={() => setAccountOpen(false)}
        onLogoutAll={() => changeIdentity(() => api('/auth/logout-all', jsonPost({})))}
        onReset={body => changeIdentity(async () => { await api('/auth/password/reset', jsonPost(body)); return api('/auth/me') })} />}
      {memoryOpen && identity.kind !== 'anonymous' && <MemoryPanel request={api} generation={memoryGeneration}
        onExpired={report} onClose={() => setMemoryOpen(false)} />}
      {source && <div className="source-overlay" onClick={() => setSource(null)}>
        <section className="source-panel" role="dialog" aria-modal="true" aria-label={source.name} onClick={e => e.stopPropagation()}>
          <div className="source-header"><div><small>原文资料</small><h2>{source.name}</h2></div><button aria-label="关闭原文" onClick={() => setSource(null)}>×</button></div>
          {source.chunks.map(chunk => <div className="source-chunk" key={chunk.index}>
            <h3>{chunk.method === 'docx' ? docxPosition(chunk) : <>{chunk.sheet ? `工作表 ${chunk.sheet} · ${chunk.range} · ` : ''}{chunk.method === 'ocr' ? 'OCR 识别，数字需核对 · ' : ''}{chunk.page ? `第 ${chunk.page} 页 · ` : ''}L{chunk.start}–{chunk.end}</>}</h3><pre>{chunk.text}</pre>
          </div>)}
        </section>
      </div>}
    </div>
  )
}
export default App
