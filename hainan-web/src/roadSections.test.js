import test from 'node:test'
import assert from 'node:assert/strict'
import { buildRoadSections, sectionIdentity, LINK_COLORS } from './roadSections.js'

const road = (id, segment, association) => ({ properties: {
  link_id: id, source_link_id: 'HN-SRC-000001', segment_index: segment,
  length_m: 100, name: '测试高速', highway: 'motorway',
  ...(association ? { business_association: { matches: association } } : {}),
} })

test('ordinary links share their original section and cycle through four colors in segment order', () => {
  const roads = [5, 3, 1, 4, 2].map(n => road(`HN-G98-M-${n}`, n))
  const { sections, byLink } = buildRoadSections(roads)
  assert.equal(sections.size, 1)
  assert.equal(sections.get('source:HN-SRC-000001').lengthM, 500)
  assert.deepEqual([1, 2, 3, 4, 5].map(n => byLink.get(`HN-G98-M-${n}`).colorIndex), [0, 1, 2, 3, 0])
  assert.equal(LINK_COLORS.length, 4)
})

test('pilot links use the strongest business match and stay distinct from ordinary sections', () => {
  const pilot = road('pilot', 1, [
    { businessLinkId: 'A', overlapM: 20, unitName: 'A 单元' },
    { businessLinkId: 'B', overlapM: 60, unitName: 'B 单元' },
  ])
  const { sections, byLink } = buildRoadSections([pilot, road('ordinary', 2)])
  assert.equal(sectionIdentity(pilot).key, 'pilot:B')
  assert.equal(sections.size, 2)
  assert.equal(byLink.get('pilot').sectionKey, 'pilot:B')
  assert.equal(byLink.get('ordinary').sectionKey, 'source:HN-SRC-000001')
})
