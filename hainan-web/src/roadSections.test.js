import test from 'node:test'
import assert from 'node:assert/strict'
import { buildRoadSections, sectionIdentity, prioritizeRoads, LINK_COLORS } from './roadSections.js'

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
  assert.deepEqual(LINK_COLORS, ['#6399CB', '#70B884', '#F2D379', '#D8886A'])
})

test('list shows mainlines before ramps and prioritizes pilot links within each type', () => {
  const mainOrdinary = road('main-ordinary', 1)
  const mainBridge = road('main-bridge', 2)
  mainBridge.properties.pilot_continuity = { status: 'topology_bridge' }
  const mainConfirmed = road('main-confirmed', 3, [{ businessLinkId: 'A' }])
  const rampOrdinary = road('ramp-ordinary', 4)
  const rampBridge = road('ramp-bridge', 5)
  rampBridge.properties.pilot_continuity = { status: 'topology_bridge' }
  const rampConfirmed = road('ramp-confirmed', 6, [{ businessLinkId: 'B' }])
  for (const ramp of [rampOrdinary, rampBridge, rampConfirmed]) ramp.properties.highway = 'motorway_link'
  const input = [rampOrdinary, mainOrdinary, rampConfirmed, mainBridge, rampBridge, mainConfirmed]
  assert.deepEqual(prioritizeRoads(input).map(feature => feature.properties.link_id),
    ['main-confirmed', 'main-bridge', 'main-ordinary', 'ramp-confirmed', 'ramp-bridge', 'ramp-ordinary'])
  assert.equal(input[0], rampOrdinary)
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

test('inferred continuity belongs to the pilot display without a business match', () => {
  const bridge = road('bridge', 3)
  bridge.properties.pilot_continuity = { status: 'topology_bridge' }
  const { sections, byLink } = buildRoadSections([road('confirmed', 1, [{ businessLinkId: 'A' }]), bridge])
  assert.equal(sectionIdentity(bridge).key, 'pilot')
  assert.equal(sections.get('pilot').roads.length, 2)
  assert.equal(byLink.get('bridge').sectionKey, 'pilot')
  assert.equal(bridge.properties.business_association, undefined)
})
