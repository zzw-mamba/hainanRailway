"""Join simple same-route motorway continuations before length-based splitting."""

from collections import defaultdict
from copy import deepcopy
import hashlib

from link_splitting import MeasuredLine, geometry_to_coordinates
from osm_topology import coordinate_key

SOURCE_ONLY_FIELDS = {'link_id', 'id', 'length', 'length_m', 'start_lng', 'start_lat',
                      'end_lng', 'end_lat', 'timestamp', 'version', 'tags', 'osm_type',
                      'source_link_id', 'segment_index'}


def _way_ids(feature):
    properties = feature['properties']
    values = properties.get('osm_way_ids')
    if values is not None:
        return list(values)
    return [properties['id']] if properties.get('id') is not None else []


def merge_highway_sources(features, index):
    """Merge only unbranched, directed motorway continuations with the same ref.

    A selected OSM node used by a third road is a junction and remains a cut.
    Roads without a confirmed OSM endpoint, unnamed routes, ramps and edited
    roads are left separate. Changing source attributes do not break the route
    chain; their intervals are retained so each child can report its provenance.
    """
    features = list(features)
    replaced = {source for feature in features
                for source in feature['properties'].get('merged_source_ids', [])
                if feature['properties'].get('manual_edit')}
    features = [feature for feature in features
                if feature['properties']['link_id'] not in replaced]
    ports = defaultdict(set)
    endpoints = {}
    for i, feature in enumerate(features):
        points = geometry_to_coordinates(feature['geometry'])
        start, end = (index.node_at(feature, point) for point in (points[0], points[-1]))
        endpoints[i] = (start, end)
        for point in points:
            node = index.node_at(feature, point)
            if node is not None:
                ports[node].add(i)

    def eligible(i):
        p = features[i]['properties']
        return (p.get('highway') == 'motorway' and bool(p.get('ref'))
                and str(p.get('oneway')) == 'yes' and not p.get('manual_edit')
                and not p.get('merged_source_ids') and len(_way_ids(features[i])) == 1)

    successors, predecessors = {}, {}
    for node, users in ports.items():
        if len(users) != 2:
            continue
        first, second = sorted(users)
        for before, after in ((first, second), (second, first)):
            if (eligible(before) and eligible(after)
                    and endpoints[before][1] == node and endpoints[after][0] == node
                    and features[before]['properties']['ref'] == features[after]['properties']['ref']
                    and coordinate_key(geometry_to_coordinates(features[before]['geometry'])[-1])
                    == coordinate_key(geometry_to_coordinates(features[after]['geometry'])[0])):
                successors[before] = after
                predecessors[after] = before

    visited, chains = set(), []
    order = sorted(range(len(features)), key=lambda i: features[i]['properties']['link_id'])
    for start in [i for i in order if i not in predecessors] + order:
        if start in visited:
            continue
        chain, current = [], start
        while current not in visited:
            visited.add(current)
            chain.append(current)
            if current not in successors:
                break
            current = successors[current]
        chains.append(chain)

    merged = []
    for chain in chains:
        if len(chain) == 1:
            merged.append(features[chain[0]])
            continue
        members = [features[i] for i in chain]
        source_ids = [f['properties']['link_id'] for f in members]
        way_ids = [value for f in members for value in _way_ids(f)]
        identifier = 'MERGED_HN_' + hashlib.sha256('\0'.join(source_ids).encode()).hexdigest()[:20]
        feature = deepcopy(members[0])
        coordinates = [list(point) for point in geometry_to_coordinates(feature['geometry'])]
        sections = []
        position = 0.0
        for member in members:
            length = MeasuredLine.from_geometry(member['geometry']).length
            properties = member['properties']
            sections.append({'source_link_id': properties['link_id'],
                             'osm_way_ids': _way_ids(member),
                             'start_m': position, 'end_m': position + length,
                             'attributes': {key: deepcopy(value) for key, value in properties.items()
                                            if key not in SOURCE_ONLY_FIELDS and value is not None}})
            position += length
        for member in members[1:]:
            coordinates.extend([list(point) for point in geometry_to_coordinates(member['geometry'])[1:]])
        feature['geometry'] = {'type': 'LineString', 'coordinates': coordinates}
        # A merged source may cross an attribute change. Avoid claiming the
        # first Way's bridge, lanes or other values describe the entire chain.
        keys = set().union(*(section['attributes'] for section in sections))
        for key in keys:
            values = [section['attributes'].get(key) for section in sections]
            if all(value == values[0] for value in values):
                feature['properties'][key] = values[0]
            else:
                feature['properties'].pop(key, None)
        for field in ('id', 'timestamp', 'version', 'tags', 'osm_type'):
            feature['properties'].pop(field, None)
        feature['properties'].update({'link_id': identifier, 'merged_source_ids': source_ids,
                                      'osm_way_ids': way_ids, 'source_sections': sections})
        merged.append(feature)
    return merged


def annotate_merged_children(children, sources):
    """Assign each child only the source attributes of the geometry it covers."""
    source_by_id = {feature['properties']['link_id']: feature for feature in sources}
    by_source = defaultdict(list)
    for child in children:
        by_source[child['properties'].get('source_link_id')].append(child)
    for source_id, group in by_source.items():
        source = source_by_id.get(source_id)
        if not source:
            continue
        if source['properties'].get('manual_edit'):
            for child in group:
                child['properties'].pop('merged_source_ids', None)
                child['properties'].pop('source_sections', None)
            continue
        sections = source['properties'].get('source_sections')
        if not sections:
            continue
        cursor = 0.0
        for child in sorted(group, key=lambda item: item['properties'].get('segment_index', 1)):
            length = MeasuredLine.from_geometry(child['geometry']).length
            start, end = cursor, cursor + length
            cursor = end
            covered = [(section, min(end, section['end_m']) - max(start, section['start_m']))
                       for section in sections if min(end, section['end_m']) - max(start, section['start_m']) > 1e-5]
            if not covered:
                raise ValueError(f'{source_id}: child has no original source section')
            properties = child['properties']
            properties.pop('merged_source_ids', None)
            properties['osm_way_ids'] = list(dict.fromkeys(
                way for section, _ in covered for way in section['osm_way_ids']))
            keys = set().union(*(section['attributes'] for section, _ in covered))
            varying = set()
            for key in keys:
                values = [section['attributes'].get(key) for section, _ in covered]
                if all(value == values[0] for value in values):
                    properties[key] = values[0]
                else:
                    properties.pop(key, None)
                    varying.add(key)
            if len(covered) > 1:
                properties['source_sections'] = [
                    {'source_link_id': section['source_link_id'], 'osm_way_ids': section['osm_way_ids'],
                     'overlap_m': round(overlap, 3),
                     'attributes': {key: section['attributes'].get(key) for key in sorted(varying)}}
                    for section, overlap in covered]
            else:
                properties.pop('source_sections', None)
