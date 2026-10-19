export const LINK_COLORS = ['#6399CB', '#70B884', '#F2D379', '#D8886A']
export const SELECTED_SECTION_COLOR = '#f5c542'

export function prioritizeRoads(roads) {
  const groups = Array.from({ length: 6 }, () => [])
  for (const feature of roads) {
    const properties = feature.properties
    const roadTypeRank = properties.highway === 'motorway' ? 0 : 1
    const pilotRank = properties.business_association?.matches?.length ? 0
      : properties.pilot_continuity?.status === 'topology_bridge' ? 1 : 2
    groups[roadTypeRank * 3 + pilotRank].push(feature)
  }
  return groups.flat()
}

export function sectionIdentity(feature) {
  const pilot = Boolean(feature.properties.business_association?.matches?.length ||
    feature.properties.pilot_continuity?.status === 'topology_bridge')
  return pilot
    ? { key: 'pilot', id: 'pilot', kind: 'pilot', name: '先导段' }
    : { key: 'ordinary', id: 'ordinary', kind: 'ordinary', name: '非先导段' }
}

export function buildRoadSections(roads) {
  const sections = new Map()
  const byLink = new Map()
  for (const feature of roads) {
    const identity = sectionIdentity(feature)
    if (!sections.has(identity.key)) sections.set(identity.key, { ...identity, roads: [], lengthM: 0 })
    const section = sections.get(identity.key)
    section.roads.push(feature)
    section.lengthM += Number(feature.properties.length_m || 0)
  }
  for (const section of sections.values()) {
    section.roads.sort((a, b) =>
      String(a.properties.ref || '').localeCompare(String(b.properties.ref || '')) ||
      String(a.properties.source_link_id || '').localeCompare(String(b.properties.source_link_id || '')) ||
      Number(a.properties.segment_index || 0) - Number(b.properties.segment_index || 0) ||
      String(a.properties.link_id).localeCompare(String(b.properties.link_id)))
    section.roads.forEach((feature, index) => byLink.set(feature.properties.link_id, {
      sectionKey: section.key,
      colorIndex: index % LINK_COLORS.length,
    }))
  }
  return { sections, byLink }
}
