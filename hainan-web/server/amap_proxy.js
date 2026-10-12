import { Readable } from 'node:stream'

// Mirrors the production /_AMapService route while testing a build locally.
export function amapProxyPlugin(securityCode) {
  function install(server) {
    server.middlewares.use(async (req, res, next) => {
      const incoming = new URL(req.url, 'http://localhost')
      if (!incoming.pathname.startsWith('/_AMapService/')) return next()
      if (!securityCode) {
        res.writeHead(503).end('AMAP_SECURITY_CODE is not configured')
        return
      }
      if (req.method !== 'GET' && req.method !== 'POST') {
        res.writeHead(405).end('Method not allowed')
        return
      }
      const path = incoming.pathname.slice('/_AMapService'.length)
      const origin = path.startsWith('/v4/map/styles')
        ? 'https://webapi.amap.com'
        : 'https://restapi.amap.com'
      const upstream = new URL(path + incoming.search, origin)
      upstream.searchParams.set('jscode', securityCode)
      const headers = {}
      for (const name of ['accept', 'content-type']) {
        if (req.headers[name]) headers[name] = req.headers[name]
      }
      try {
        const response = await fetch(upstream, {
          method: req.method,
          headers,
          body: req.method === 'POST' ? req : undefined,
          duplex: req.method === 'POST' ? 'half' : undefined,
          redirect: 'error',
        })
        const responseHeaders = {}
        for (const name of ['content-type', 'cache-control']) {
          const value = response.headers.get(name)
          if (value) responseHeaders[name] = value
        }
        res.writeHead(response.status, responseHeaders)
        if (response.body) Readable.fromWeb(response.body).pipe(res)
        else res.end()
      } catch {
        res.writeHead(502).end('AMap proxy request failed')
      }
    })
  }
  return { name: 'amap-local-proxy', configureServer: install, configurePreviewServer: install }
}
