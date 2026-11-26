import test from 'node:test'
import assert from 'node:assert/strict'
import { request } from '../frontend/src/request.js'
const reply = (status, body, type = 'application/json') => new Response(body, {status, headers: {'content-type': type}})
test('JSON success preserves credentials and request options', async () => {
  globalThis.fetch = async (path, options) => { assert.equal(path, '/auth/register'); assert.equal(options.credentials, 'include'); assert.equal(options.method, 'POST'); return reply(200, '{"ok":true}') }
  assert.deepEqual(await request('/auth/register', {method:'POST'}), {ok:true})
})
test('application JSON 401 keeps status for normal expiry handling', async () => {
  globalThis.fetch = async () => reply(401, '{"detail":"登录已过期"}')
  await assert.rejects(request('/auth/me'), e => e.status === 401 && e.message === '登录已过期')
})
test('gateway text 401 is not application expiry', async () => {
  globalThis.fetch = async () => reply(401, 'Unauthorized', 'text/plain')
  await assert.rejects(request('/auth/register'), e => e.status === undefined && e.gatewayStatus === 401 && e.message.includes('公网访问层'))
})
test('gateway HTML 502 is not parsed or echoed', async () => {
  globalThis.fetch = async () => reply(502, '<script>private-proxy-content</script>', 'text/html')
  await assert.rejects(request('/auth/me'), e => e.message.includes('502') && !e.message.includes('private-proxy-content'))
})
test('network/CORS failure is not reported as wrong password', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(request('/auth/login'), e => e.status === undefined && e.message.includes('不代表用户名或密码错误'))
})
test('abort is preserved', async () => {
  const err = new DOMException('aborted', 'AbortError'); globalThis.fetch = async () => { throw err }
  await assert.rejects(request('/history'), e => e === err)
})
test('malformed JSON gets a bounded error', async () => {
  globalThis.fetch = async () => reply(200, 'bad json')
  await assert.rejects(request('/history'), /JSON响应格式无效/)
})
test('structured JSON suffix is accepted', async () => {
  globalThis.fetch = async () => reply(422, '{"detail":"invalid input"}', 'application/problem+json')
  await assert.rejects(request('/auth/register'), e => e.status === 422 && e.message === 'invalid input')
})
