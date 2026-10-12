import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))
export const validLength = value => typeof value === 'number' && Number.isFinite(value) && value >= 100 && value <= 10000

export function generationPlugin() {
  let job = null
  let child = null
  const send = (res, code, value) => {
    res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
    res.end(JSON.stringify(value))
  }
  function install(server) {
    // Both dev and preview serve the current snapshot after successful regeneration.
    server.middlewares.use(async (req, res, next) => {
      const url = new URL(req.url, 'http://localhost')
      if (url.pathname === '/data/hainan.json' && req.method === 'GET') {
        try {
          const content = await readFile(new URL('../public/data/hainan.json', import.meta.url))
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
          res.end(content)
        } catch { send(res, 503, { error: '当前数据快照无法读取，请重试' }) }
        return
      }
      const editing = url.pathname === '/api/link-edit'
      if (url.pathname !== '/api/generation' && !editing) return next()
      if (!editing && req.method === 'GET') return send(res, 200, job || { status: 'idle' })
      if (req.method !== 'POST') return send(res, 405, { error: '不支持该请求方法' })
      const origin = req.headers.origin
      if (origin && origin !== `http://${req.headers.host}` && origin !== `https://${req.headers.host}`) {
        return send(res, 403, { error: '仅接受当前页面发起的生成请求' })
      }
      if (child) return send(res, 409, { error: '正在生成，请等待完成', job })
      let body = ''
      try {
        for await (const chunk of req) {
          body += chunk
          if (body.length > (editing ? 2_000_000 : 1024)) return send(res, 413, { error: '请求过大' })
        }
        const request = JSON.parse(body)
        const { maxLinkLengthM } = request
        if (!validLength(maxLinkLengthM)) return send(res, 400, { error: '最大长度需在 100–10,000 m 之间' })
        if (editing && !['add', 'update', 'delete', 'delete_source'].includes(request.action)) {
          return send(res, 400, { error: '不支持的路链编辑操作' })
        }
        // Re-check after the asynchronous body read so concurrent requests cannot overlap.
        if (child) return send(res, 409, { error: '正在生成，请等待完成', job })
        job = { id: randomUUID(), status: 'running', kind: editing ? 'edit' : 'regenerate',
          maxLinkLengthM, message: editing ? '正在保存路链编辑并更新拆分…' : '正在读取原始路网…', startedAt: Date.now() }
        child = spawn('python3', ['-u', 'hainan-web/scripts/generate_data.py', '--max-link-length', String(maxLinkLengthM),
          ...(editing ? ['--edit-stdin'] : [])],
          { cwd: root, stdio: [editing ? 'pipe' : 'ignore', 'pipe', 'pipe'] })
        if (editing) child.stdin.end(body)
        const taskProcess = child
        let failure = ''
        const timeout = setTimeout(() => { failure = '生成超时，请重试或提高最大长度'; taskProcess.kill('SIGTERM') }, 300000)
        taskProcess.stdout.on('data', chunk => {
          const lines = chunk.toString().trim().split('\n')
          job.message = lines.at(-1) || job.message
        })
        taskProcess.stderr.on('data', chunk => { failure = (failure + chunk.toString()).slice(-2000) })
        const finish = (success, error) => {
          clearTimeout(timeout)
          if (child !== taskProcess) return
          job = { ...job, status: success ? 'done' : 'failed', finishedAt: Date.now(),
            message: success ? '生成完成' : (error || '生成失败，保留上一次路网') }
          child = null
        }
        taskProcess.once('error', () => finish(false, '无法启动 Python 生成脚本，请检查本地 Python 3 环境'))
        taskProcess.once('close', code => finish(code === 0, failure))
        send(res, 202, job)
      } catch { send(res, 400, { error: '生成参数格式错误' }) }
    })
    server.httpServer?.once('close', () => child?.kill('SIGTERM'))
  }
  return { name: 'hainan-local-generation', configureServer: install, configurePreviewServer: install }
}
