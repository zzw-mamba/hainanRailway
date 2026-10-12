import test from 'node:test'
import assert from 'node:assert/strict'
import { Readable } from 'node:stream'
import { generationPlugin } from './generation.js'

async function request({ method = 'POST', body = '{}', origin, path = '/api/generation' } = {}) {
  let middleware
  generationPlugin().configureServer({ middlewares: { use: handler => { middleware = handler } } })
  const req = Readable.from([body])
  Object.assign(req, { method, url: path, headers: { host: '127.0.0.1:5173', ...(origin ? { origin } : {}) } })
  let code, value, passed = false
  const res = { writeHead: status => { code = status }, end: text => { value = JSON.parse(text) } }
  await middleware(req, res, () => { passed = true })
  return { code, value, passed }
}

test('rejects invalid lengths and malformed JSON before starting a task', async () => {
  for (const maxLinkLengthM of [0, 99, 10001, '500', null]) {
    assert.equal((await request({ body: JSON.stringify({ maxLinkLengthM }) })).code, 400)
  }
  assert.equal((await request({ body: '{invalid' })).code, 400)
})

test('rejects another page origin and oversized request', async () => {
  assert.equal((await request({ origin: 'https://another.example', body: '{"maxLinkLengthM":500}' })).code, 403)
  assert.equal((await request({ body: 'x'.repeat(1025) })).code, 413)
})

test('idle status and method restrictions remain available', async () => {
  assert.deepEqual((await request({ method: 'GET' })).value, { status: 'idle' })
  assert.equal((await request({ method: 'DELETE' })).code, 405)
})

test('leaves normal web routes to Vite', async () => {
  assert.equal((await request({ method: 'GET', path: '/' })).passed, true)
})

test('edit endpoint rejects invalid action, length, and foreign origin', async () => {
  const path = '/api/link-edit'
  assert.equal((await request({ path, body: JSON.stringify({ action: 'erase', maxLinkLengthM: 500 }) })).code, 400)
  assert.equal((await request({ path, body: JSON.stringify({ action: 'delete', maxLinkLengthM: 50 }) })).code, 400)
  assert.equal((await request({ path, origin: 'https://another.example',
    body: JSON.stringify({ action: 'delete', maxLinkLengthM: 500 }) })).code, 403)
  assert.equal((await request({ path, method: 'GET' })).code, 405)
})
