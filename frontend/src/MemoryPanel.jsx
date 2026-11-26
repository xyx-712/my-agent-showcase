import { useEffect, useEffectEvent, useRef, useState } from 'react'
import './MemoryPanel.css'

const category = key => ['name', 'job'].includes(key) ? 'profile' : ['hobby', 'likes', 'skill'].includes(key) ? 'preferences' : key.startsWith('project') ? 'projects' : 'other'
const names = { name: '姓名', job: '职业', hobby: '爱好', likes: '偏好', skill: '技能' }
const sources = { legacy: '旧记录 · 来源未知', internal: '内部记录', user_statement: '用户陈述', user_correction: '用户更正', user_restore: '用户明确恢复', user_management: '手动管理', model_candidate: '模型候选' }
const confirmations = { unknown: '未知', user_stated: '用户已陈述', user_confirmed: '用户已确认', pending: '待确认' }
const statuses = { active: '有效', pending_confirmation: '存在待确认信息', deleted: '已删除 · 当前无效' }
const date = value => value ? new Date(value).toLocaleString() : '未知（旧记录）'
const body = value => ({ method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })

export default function MemoryPanel({ request, generation, onExpired, onClose }) {
  const [items, setItems] = useState([])
  const [settings, setSettings] = useState(null)
  const [group, setGroup] = useState('all')
  const [deleted, setDeleted] = useState(false)
  const [detail, setDetail] = useState(null)
  const [draft, setDraft] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [busy, setBusy] = useState(true)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const life = useRef({ alive: true, sequence: 0, controller: null })

  function begin() {
    life.current.controller?.abort()
    life.current.controller = new AbortController()
    const sequence = ++life.current.sequence
    setBusy(true); setError('')
    return { sequence, signal: life.current.controller.signal }
  }
  const valid = sequence => life.current.alive && life.current.sequence === sequence
  function fail(err, sequence) {
    if (!valid(sequence) || err.name === 'AbortError') return
    setError(err.status === 409 ? `${err.message}。请重新载入后核对，当前编辑内容尚未保存。` : err.message)
    if (err.status === 401) onExpired(err, generation)
  }
  async function load(message = '', clear = true) {
    const { sequence, signal } = begin()
    try {
      const [rows, automatic] = await Promise.all([request(`/memories?include_deleted=${deleted}`, { signal }), request('/memories/settings', { signal })])
      if (!valid(sequence)) return
      setItems(rows.items); setHasMore(rows.has_more); setSettings(automatic); setNotice(message)
      if (clear) { setDetail(null); setDraft(''); setAcknowledged(false) }
    } catch (err) { fail(err, sequence) }
    finally { if (valid(sequence)) setBusy(false) }
  }
  const initialLoad = useEffectEvent(() => load())
  useEffect(() => {
    const current = life.current
    current.alive = true
    const timer = setTimeout(() => initialLoad(), 0)
    return () => { clearTimeout(timer); current.alive = false; current.sequence++; current.controller?.abort() }
  }, [generation, deleted])
  useEffect(() => {
    const escape = event => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onClose])

  async function select(item) {
    const { sequence, signal } = begin()
    try {
      const value = await request(`/memories/${item.id}`, { signal })
      if (!valid(sequence)) return
      setDetail(value); setDraft(value.item.value); setAcknowledged(false); setNotice('')
    } catch (err) { fail(err, sequence) }
    finally { if (valid(sequence)) setBusy(false) }
  }
  async function mutate(path, options, message, clear = true) {
    const { sequence, signal } = begin()
    try {
      await request(path, { ...options, signal })
      if (valid(sequence)) await load(message, clear)
    } catch (err) { fail(err, sequence) }
    finally { if (valid(sequence)) setBusy(false) }
  }
  const item = detail?.item
  return <div className="source-overlay" onClick={onClose}>
    <section className="memory-panel" role="dialog" aria-modal="true" aria-label="长期记忆管理" onClick={event => event.stopPropagation()}>
      <div className="source-header"><div><small>由你掌握的信息</small><h2>长期记忆</h2></div><button aria-label="关闭记忆管理" onClick={onClose}>×</button></div>
      <div className="memory-toolbar">
        <label><input type="checkbox" aria-label="自动记忆" checked={settings?.automatic_enabled ?? false} disabled={busy || !settings}
          onChange={event => mutate('/memories/settings', body({ automatic_enabled: event.target.checked, revision: settings.revision }), event.target.checked ? '自动记忆已开启' : '自动记忆已暂停', false)} /> 自动记忆</label>
        <span>{settings ? settings.automatic_enabled ? '按写入策略保存新信息' : '已暂停；已有记忆仍可使用和管理' : '正在加载…'}</span>
        <button disabled={busy} onClick={() => load()}>重新载入</button>
      </div>
      <div className="memory-filters"><label>类别 <select aria-label="记忆类别" value={group} onChange={event => setGroup(event.target.value)}>
        <option value="all">全部</option><option value="profile">个人信息</option><option value="preferences">兴趣与偏好</option><option value="projects">项目背景</option><option value="other">其他</option>
      </select></label><label><input type="checkbox" checked={deleted} disabled={busy} onChange={event => setDeleted(event.target.checked)} /> 显示已删除</label></div>
      {notice && <p className="memory-success" role="status">{notice}</p>}{error && <p className="memory-error" role="alert">{error}</p>}
      {hasMore && <p>当前仅显示前200项；完整历史仍保存在数据库中。</p>}
      <div className="memory-columns"><div className="memory-list">
        {!busy && !items.filter(row => group === 'all' || category(row.key) === group).length && <p className="memory-empty">这个类别还没有记忆。</p>}
        {items.filter(row => group === 'all' || category(row.key) === group).map(row => <button className={`memory-record ${item?.id === row.id ? 'selected' : ''}`} key={row.id} disabled={busy} onClick={() => select(row)}>
          <strong>{names[row.key] || row.key}</strong><span>{row.status === 'deleted' ? '已删除的内容' : row.value || '候选信息待确认'}</span>
          <small>{statuses[row.status]} · v{row.revision}</small><small>{sources[row.source_type] || row.source_type}</small>
        </button>)}
      </div><div className="memory-detail">
        {!item ? <p className="memory-empty">选择一条记忆，查看来源和修订记录。</p> : <>
          <h3>{names[item.key] || item.key}</h3>
          <dl><dt>状态</dt><dd>{statuses[item.status]}</dd><dt>来源</dt><dd>{sources[item.source_type] || item.source_type}</dd>
            <dt>确认</dt><dd>{confirmations[item.confirmation_state] || item.confirmation_state}</dd><dt>修订</dt><dd>v{item.revision}</dd>
            <dt>创建</dt><dd>{date(item.created_at)}</dd><dt>更新</dt><dd>{date(item.updated_at)}</dd></dl>
          <label>记忆内容<textarea aria-label="记忆内容" value={draft} maxLength={6000} disabled={busy || item.status === 'deleted'} onChange={event => setDraft(event.target.value)} /></label>
          {detail.candidates.length > 0 && <details><summary>待确认候选</summary>{detail.candidates.map(candidate => <p key={candidate.id}>{candidate.value}</p>)}</details>}
          <button className="memory-save" disabled={busy || !draft.trim() || item.status === 'deleted'} onClick={() => mutate(`/memories/${item.id}`, body({ value: draft, revision: item.revision }), '记忆已保存，已生成新修订')}>保存修改</button>
          <details><summary>来源与修订记录</summary>
            <p>{detail.source?.type === 'message' ? `来源消息 #${detail.source.id}：${detail.source.content}` : detail.source?.type === 'management' ? `管理操作：${detail.source.action.action} · ${date(detail.source.action.created_at)}` : '历史来源未知，未补造来源。'}</p>
            {detail.versions.map(version => <div className="memory-version" key={version.revision}><strong>v{version.revision} · {statuses[version.status]}</strong><p>{version.value || '无有效值'}</p><small>{date(version.updated_at)}</small></div>)}
          </details>
          <div className="memory-delete"><p>删除长期记忆不等于删除原始聊天记录和备份。</p>
            <label><input type="checkbox" checked={acknowledged} disabled={busy || item.status === 'deleted'} onChange={event => setAcknowledged(event.target.checked)} /> 我了解删除范围</label>
            <button disabled={busy || !acknowledged || item.status === 'deleted'} onClick={() => mutate(`/memories/${item.id}`, { ...body({ revision: item.revision }), method: 'DELETE' }, '记忆已删除，不再作为有效长期记忆使用')}>删除记忆</button>
          </div>
        </>}
      </div></div>
    </section>
  </div>
}
