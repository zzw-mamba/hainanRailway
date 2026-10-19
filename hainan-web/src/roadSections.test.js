import test from 'node:test'
import assert from 'node:assert/strict'
import { buildRoadSections, sectionIdentity, LINK_COLORS } from './roadSections.js'

const road = (id, segment, association) => ({ properties: {
  link_id: id, source_link_id: 'HN-SRC-000001', segment_index: segment,
  length_m: 100, name: '测试高速', highway: 'motorway',
  ...(association ? { business_association: { matches: association } } : {}),
} })

test('all ordinary links form one section and cycle through four colors', () => {
  const roads = [5, 3, 1, 4, 2].map(n => road(`HN-G98-M-${n}`, n))
  const { sections, byLink } = buildRoadSections(roads)
  assert.equal(sections.size, 1)
  assert.equal(sections.get('ordinary').lengthM, 500)
  assert.deepEqual([1, 2, 3, 4, 5].map(n => byLink.get(`HN-G98-M-${n}`).colorIndex), [0, 1, 2, 3, 0])
  assert.equal(LINK_COLORS.length, 4)
})

test('all associated links form the pilot section even with different business IDs', () => {
  const first = road('pilot-a', 1, [{ businessLinkId: 'A', overlapM: 20 }])
  const second = road('pilot-b', 2, [{ businessLinkId: 'B', overlapM: 60 }])
  const { sections, byLink } = buildRoadSections([first, second, road('ordinary', 3)])
  assert.equal(sectionIdentity(first).key, 'pilot')
  assert.equal(sections.size, 2)
  assert.equal(sections.get('pilot').roads.length, 2)
  assert.equal(byLink.get('pilot-a').sectionKey, 'pilot')
  assert.equal(byLink.get('pilot-b').sectionKey, 'pilot')
  assert.equal(byLink.get('ordinary').sectionKey, 'ordinary')
})
