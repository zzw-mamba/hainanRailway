"""Join simple same-route motorway continuations before length-based splitting."""

from collections import defaultdict
from copy import deepcopy
import hashlib

from link_splitting import geometry_to_coordinates
from osm_topology import coordinate_key

MERGE_FIELDS = ('name', 'lanes', 'maxspeed', 'surface', 'bridge', 'tunnel',
                'access', 'motor_vehicle', 'motorroad')


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
    roads are left separate. Original source IDs and Way IDs remain traceable.
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
                    and all(features[before]['properties'].get(field) == features[after]['properties'].get(field)
                            for field in MERGE_FIELDS)
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
        for member in members[1:]:
            coordinates.extend([list(point) for point in geometry_to_coordinates(member['geometry'])[1:]])
        feature['geometry'] = {'type': 'LineString', 'coordinates': coordinates}
        for field in ('id', 'timestamp', 'version', 'tags', 'osm_type'):
            feature['properties'].pop(field, None)
        feature['properties'].update({'link_id': identifier, 'merged_source_ids': source_ids,
                                      'osm_way_ids': way_ids})
        merged.append(feature)
    return merged
