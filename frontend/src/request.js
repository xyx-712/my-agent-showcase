// Gateway authentication errors must not be treated as application-session expiry.
export async function request(path, options = {}) {
  let response
  try {
    response = await fetch(path, { credentials: 'include', ...options })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    throw new Error('请求未能完成：请检查后端连接及公网访问认证状态。此错误不代表用户名或密码错误。')
  }
  const type = response.headers.get('content-type') || ''
  if (!/\bapplication\/(?:[\w.+-]+\+)?json\b/i.test(type)) {
    // Do not display arbitrary proxy HTML/text or attach application-auth status.
    const error = new Error(response.status === 401 || response.status === 403
      ? '公网访问层返回了非JSON的拒绝响应。请检查隧道认证；尚不能判断应用登录结果。'
      : `服务返回非JSON响应（HTTP ${response.status}），请检查后端或公网访问层。`)
    error.gatewayStatus = response.status
    throw error
  }
  let data
  try { data = await response.json() }
  catch { throw new Error('服务返回的JSON响应格式无效，请检查服务日志。') }
  if (!response.ok) {
    const error = new Error(typeof data?.detail === 'string' ? data.detail : '输入格式不正确，请检查字段内容')
    error.status = response.status
    throw error
  }
  return data
}
