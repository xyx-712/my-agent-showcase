import { useEffect, useRef, useState } from 'react'

export default function AccountPanel({ identity, request, onClose, onLogoutAll, onReset }) {
  const active = useRef(true)
  const [sessions, setSessions] = useState([])
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [message, setMessage] = useState('')
  const [working, setWorking] = useState(false)
  useEffect(() => {
    active.current = true
    if (identity.kind === 'account') {
      request('/auth/sessions').then(data => { if (active.current) setSessions(data.sessions) })
        .catch(error => { if (active.current) setMessage(error.message) })
    }
    return () => { active.current = false }
  }, [identity.kind, request])
  async function action(path, body, success) {
    setWorking(true)
    try {
      const result = await request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!active.current) return
      setMessage(result.message || success)
      setCurrentPassword('')
      setNewPassword('')
      setToken('')
      if (identity.kind === 'account') {
        const data = await request('/auth/sessions')
        if (active.current) setSessions(data.sessions)
      }
    } catch (error) { if (active.current) setMessage(error.message) }
    finally { if (active.current) setWorking(false) }
  }
  return <div className="source-overlay"><section className="auth-panel" role="dialog" aria-label="账号管理" aria-modal="true">
    <button className="guest-button" onClick={onClose}>关闭</button>
    <h2>{identity.kind === 'account' ? '账号管理' : '密码找回'}</h2>
    {identity.kind === 'account' && <>
      <label>当前密码<input type="password" autoComplete="current-password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} /></label>
      <label>新密码<input type="password" autoComplete="new-password" value={newPassword} onChange={e => setNewPassword(e.target.value)} /></label>
      <button disabled={working || newPassword.length < 10} onClick={() => action('/auth/password/change', { current_password: currentPassword, new_password: newPassword }, '密码已修改，其他设备已退出')}>修改密码</button>
      <h3>登录设备</h3>
      {sessions.map(session => <div className="session-row" key={session.id}>
        <small>{session.current ? '当前设备 · ' : ''}{session.device}</small>
        {!session.current && <button disabled={working} onClick={() => action('/auth/sessions/revoke', { id: session.id }, '设备已退出')}>撤销</button>}
      </div>)}
      <button disabled={working} onClick={onLogoutAll}>退出所有设备</button>
    </>}
    <h3>邮箱验证与密码找回</h3>
    <p>邮件服务需由运行者配置。一次性令牌有效期十五分钟。</p>
    <label>邮箱<input type="email" value={email} onChange={e => setEmail(e.target.value)} /></label>
    {identity.kind === 'account' && <button disabled={working} onClick={() => action('/auth/email/request', { email, current_password: currentPassword }, '验证邮件已发送')}>发送邮箱验证</button>}
    <button disabled={working} onClick={() => action('/auth/password/forgot', { email }, '请求已接受')}>发送密码重置邮件</button>
    <label>邮件中的一次性令牌<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label>
    {identity.kind === 'account' && <button disabled={working} onClick={() => action('/auth/email/verify', { token }, '邮箱已验证')}>确认邮箱验证</button>}
    <label>重置后的密码<input type="password" autoComplete="new-password" value={newPassword} onChange={e => setNewPassword(e.target.value)} /></label>
    <button disabled={working || token.length !== 43 || newPassword.length < 10} onClick={() => onReset({ token, new_password: newPassword })}>验证令牌并重置密码</button>
    <p role="status">{message}</p>
  </section></div>
}
