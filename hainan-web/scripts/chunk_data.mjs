import { readFile, mkdir, readdir, rm, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { gzipSync } from 'node:zlib'

const source = new URL('../public/data/hainan.json', import.meta.url)
const output = new URL('../public/data/stream/', import.meta.url)
const chunkSize = 750
const raw = await readFile(source)
const payload = JSON.parse(raw.toString('utf8'))
await mkdir(output, { recursive: true })
for (const name of await readdir(output)) {
  if (/^(roads-\d+|relationships|manifest)\.json(\.gz)?$/.test(name)) await rm(new URL(name, output))
}

async function writeJson(name, value) {
  const content = Buffer.from(JSON.stringify(value))
  await Promise.all([
    writeFile(new URL(name, output), content),
    writeFile(new URL(`${name}.gz`, output), gzipSync(content, { level: 9 })),
  ])
}
const chunks = []
for (let start = 0; start < payload.roads.length; start += chunkSize) {
  const name = `roads-${String(chunks.length + 1).padStart(3, '0')}.json`
  await writeJson(name, payload.roads.slice(start, start + chunkSize))
  chunks.push(name)
}
await writeJson('relationships.json', payload.relationships)
const { roads, relationships, ...summary } = payload
const extent = [Infinity, Infinity, -Infinity, -Infinity]
for (const feature of roads) {
  const parts = feature.geometry.type === 'LineString'
    ? [feature.geometry.coordinates] : feature.geometry.coordinates
  for (const part of parts) for (const [lng, lat] of part) {
    extent[0] = Math.min(extent[0], lng)
    extent[1] = Math.min(extent[1], lat)
    extent[2] = Math.max(extent[2], lng)
    extent[3] = Math.max(extent[3], lat)
  }
}
await writeJson('manifest.json', {
  ...summary,
  roadCount: roads.length,
  relationshipCount: relationships.length,
  roadChunks: chunks,
  extent,
  snapshotId: createHash('sha256').update(raw).digest('hex').slice(0, 16),
})
console.log(`Prepared ${roads.length} roads in ${chunks.length} chunks`)
