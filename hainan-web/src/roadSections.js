export const LINK_COLORS = ['#137f78', '#d88438', '#7654bb', '#ca5873']
export const SELECTED_SECTION_COLOR = '#f5c542'

export function sectionIdentity(feature) {
  const properties = feature.properties
  const matches = properties.business_association?.matches || []
  if (matches.length) {
    const match = [...matches].sort((a, b) =>
      Number(b.overlapM || 0) - Number(a.overlapM || 0) ||
      String(a.businessLinkId).localeCompare(String(b.businessLinkId)))[0]
    return {
      key: `pilot:${match.businessLinkId}`,
      id: String(match.businessLinkId),
      kind: 'pilot',
      name: match.unitName || properties.name || '未命名先导段',
    }
  }
  const id = String(properties.source_link_id || properties.osm_source_link_id || properties.link_id)
  return {
    key: `source:${id}`,
    id,
    kind: 'ordinary',
    name: properties.name || properties.ref || (properties.highway === 'motorway' ? '未命名高速主线' : '未命名高速匝道'),
  }
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
