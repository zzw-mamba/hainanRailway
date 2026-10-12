// Cloudflare Pages advanced mode: keep the AMap security code in a Pages secret.
// All other requests are served from the Vite static build.
export default {
  async fetch(request, env) {
    const incoming = new URL(request.url)
    const prefix = '/_AMapService/'
    if (!incoming.pathname.startsWith(prefix)) return env.ASSETS.fetch(request)

    if (!env.AMAP_SECURITY_CODE) {
      return new Response('AMAP_SECURITY_CODE is not configured', { status: 503 })
    }
    if (request.method !== 'GET' && request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 })
    }

    const path = incoming.pathname.slice('/_AMapService'.length)
    const origin = path.startsWith('/v4/map/styles')
      ? 'https://webapi.amap.com'
      : 'https://restapi.amap.com'
    const upstream = new URL(path + incoming.search, origin)
    upstream.searchParams.set('jscode', env.AMAP_SECURITY_CODE)

    const headers = new Headers()
    for (const name of ['accept', 'content-type']) {
      const value = request.headers.get(name)
      if (value) headers.set(name, value)
    }
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.method === 'POST' ? request.body : undefined,
      redirect: 'error',
    })
    const responseHeaders = new Headers()
    for (const name of ['content-type', 'cache-control']) {
      const value = response.headers.get(name)
      if (value) responseHeaders.set(name, value)
    }
    return new Response(response.body, { status: response.status, headers: responseHeaders })
  },
}
