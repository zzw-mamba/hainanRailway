"""Directed Link topology confirmed by shared OSM node references in the PBF.

Coordinates are used to recover a node on its own source Way, never to join
unrelated Ways. Synthetic length cuts are scoped to their original Link.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from inspect_pbf_highways import _fields, _read_blocks
from extract_motorway_junctions import _packed_signed, _signed
from link_splitting import MeasuredLine, geometry_to_coordinates


def coordinate_key(point):
    return tuple(round(float(value), 7) for value in point[:2])


def way_id(feature):
    try:
        return int(feature['properties']['id'])
    except (KeyError, TypeError, ValueError):
        return None


@dataclass
class NodeIndex:
    way_nodes: dict
    coordinates: dict

    def __post_init__(self):
        self.by_way = {}
        for way, nodes in self.way_nodes.items():
            positions = defaultdict(set)
            for node in nodes:
                if node in self.coordinates:
                    positions[coordinate_key(self.coordinates[node])].add(node)
            self.by_way[way] = positions

    def node_at(self, feature, point):
        nodes = self.by_way.get(way_id(feature), {}).get(coordinate_key(point), set())
        return next(iter(nodes)) if len(nodes) == 1 else None


def extract_node_index(pbf_path, features):
    """Two streaming passes: selected Way refs, then only their Node coordinates."""
    wanted_ways = {way_id(f) for f in features} - {None}
    way_nodes = {}
    for kind, block in _read_blocks(Path(pbf_path)):
        if kind != 'OSMData':
            continue
        for field, _, group in _fields(block):
            if field != 2:
                continue
            for number, _, payload in _fields(group):
                if number != 3:
                    continue
                values = dict((field, value) for field, _, value in _fields(payload))
                identifier = int(values[1])
                if identifier not in wanted_ways:
                    continue
                current, nodes = 0, []
                for delta in _packed_signed(values.get(8, memoryview(b''))):
                    current += delta
                    nodes.append(current)
                way_nodes[identifier] = nodes
    wanted_nodes = {node for nodes in way_nodes.values() for node in nodes}
    coordinates = {}
    for kind, block in _read_blocks(Path(pbf_path)):
        if kind != 'OSMData':
            continue
        fields = list(_fields(block))
        metadata = {number: value for number, _, value in fields if number in (17, 19, 20)}
        granularity = int(metadata.get(17, 100))
        lat_offset, lon_offset = int(metadata.get(19, 0)), int(metadata.get(20, 0))
        # PrimitiveBlock offsets are int64, not zigzag sint64.
        lat_offset = lat_offset - 2**64 if lat_offset >= 2**63 else lat_offset
        lon_offset = lon_offset - 2**64 if lon_offset >= 2**63 else lon_offset
        def retain(node, lat, lon):
            if node in wanted_nodes:
                coordinates[node] = (1e-9 * (lon_offset + granularity * lon),
                                     1e-9 * (lat_offset + granularity * lat))
        for field, _, group in fields:
            if field != 2:
                continue
            for number, _, payload in _fields(group):
                if number == 1:
                    values = {f: v for f, _, v in _fields(payload)}
                    retain(_signed(int(values[1])), _signed(int(values[8])), _signed(int(values[9])))
                elif number == 2:
                    values = {f: v for f, _, v in _fields(payload)}
                    ids, lats, lons = [_packed_signed(values.get(f, memoryview(b''))) for f in (1, 8, 9)]
                    if not len(ids) == len(lats) == len(lons):
                        raise ValueError('PBF DenseNodes coordinate arrays differ in length')
                    node = lat = lon = 0
                    for di, dy, dx in zip(ids, lats, lons):
                        node, lat, lon = node + di, lat + dy, lon + dx
                        retain(node, lat, lon)
    return NodeIndex(way_nodes, coordinates)


def junction_cuts(features, index, metric_mode='auto'):
    """Cut a source Link at vertices shared with another source Link."""
    users = defaultdict(set)
    lines = {}
    for feature in features:
        source = feature['properties']['link_id']
        line = MeasuredLine.from_geometry(feature['geometry'], metric_mode)
        lines[source] = line
        for point in line.coordinates:
            node = index.node_at(feature, point)
            if node is not None:
                users[node].add(source)
    shared = {node for node, sources in users.items() if len(sources) > 1}
    cuts = {}
    for feature in features:
        source = feature['properties']['link_id']
        line = lines[source]
        measures = [line.measures[i] for i, point in enumerate(line.coordinates)
                    if 0 < i < len(line.coordinates) - 1 and index.node_at(feature, point) in shared]
        if measures:
            cuts[source] = measures
    return cuts


def travel_orientations(properties):
    value = str(properties.get('oneway', '')).lower()
    if value in ('yes', '1', 'true'):
        return ('forward',)
    if value == '-1':
        return ('reverse',)
    if value in ('no', '0', 'false'):
        return ('forward', 'reverse')
    return ()


def build_topology(features, index):
    """Build direction-specific transitions, including splits and cross-source links."""
    ids = [f['properties']['link_id'] for f in features]
    if len(ids) != len(set(ids)):
        raise ValueError('Topology input contains duplicate Link IDs')
    entering, leaving, records = defaultdict(list), defaultdict(list), {}
    unknown_direction = []
    node_sources = defaultdict(set)
    feature_interior_nodes = {}
    for feature in features:
        p = feature['properties']
        identifier = p['link_id']
        source = p.get('source_link_id') or identifier
        points = geometry_to_coordinates(feature['geometry'])
        nodes, osm_nodes = [], []
        for point in (points[0], points[-1]):
            osm_node = index.node_at(feature, point)
            osm_nodes.append(osm_node)
            position = coordinate_key(point)
            nodes.append(f'osm:{osm_node}' if osm_node is not None else f'split:{source}:{position[0]:.7f},{position[1]:.7f}')
        orientations = travel_orientations(p)
        p['topology'] = {'startNode': nodes[0], 'endNode': nodes[1],
                         'startOsmNodeId': osm_nodes[0], 'endOsmNodeId': osm_nodes[1],
                         'directionStatus': 'confirmed' if orientations else 'unknown'}
        records[identifier] = {'source': source, 'nodes': nodes, 'points': points,
                               'orientations': orientations, 'osmNodes': osm_nodes}
        interior = set()
        for point_index, point in enumerate(points):
            osm_node = index.node_at(feature, point)
            if osm_node is not None:
                node_sources[osm_node].add(source)
                if 0 < point_index < len(points) - 1:
                    interior.add(osm_node)
        feature_interior_nodes[identifier] = interior
        if not orientations:
            unknown_direction.append(identifier)
        for orientation in orientations:
            first, last = (0, 1) if orientation == 'forward' else (1, 0)
            leaving[nodes[first]].append((identifier, orientation))
            entering[nodes[last]].append((identifier, orientation))
    relationships = []
    for node in sorted(entering.keys() & leaving.keys()):
        for current, current_orientation in sorted(entering[node]):
            for following, following_orientation in sorted(leaving[node]):
                if current == following:
                    continue  # No immediate U-turn onto the same Link.
                internal = records[current]['source'] == records[following]['source']
                if not internal and not node.startswith('osm:'):
                    continue
                kind = 'split_internal' if internal else 'osm_cross_source'
                signature = json.dumps([current, following, node, current_orientation, following_orientation], separators=(',', ':'))
                row = {'id': 'OSM_REL_' + hashlib.sha256(signature.encode()).hexdigest()[:24],
                       'currentLinkId': current, 'nextLinkId': following, 'relationship_type': kind,
                       'currentOrientation': current_orientation, 'nextOrientation': following_orientation,
                       'junctionNode': node, 'osmNodeId': int(node[4:]) if node.startswith('osm:') else None,
                       'basis': 'osm_shared_node' if node.startswith('osm:') else 'same_source_split'}
                if internal:
                    row['source_link_id'] = records[current]['source']
                relationships.append(row)
    has_incoming = {r['nextLinkId'] for r in relationships}
    has_outgoing = {r['currentLinkId'] for r in relationships}
    pending = []
    for identifier, record in records.items():
        missing = []
        for orientation in record['orientations']:
            first, last = (0, 1) if orientation == 'forward' else (1, 0)
            for role, endpoint, peers in [('incoming', first, entering), ('outgoing', last, leaving)]:
                if not any(other != identifier for other, _ in peers.get(record['nodes'][endpoint], [])):
                    missing.append({'role': role, 'orientation': orientation, 'osmNodeId': record['osmNodes'][endpoint],
                                    'wgs84': list(record['points'][0 if endpoint == 0 else -1])})
        if missing or not record['orientations']:
            pending.append({'linkId': identifier, 'sourceLinkId': record['source'],
                            'reason': 'unknownDirection' if not record['orientations'] else 'networkBoundaryOrUnresolvedConnection',
                            'missingConnections': missing})
    counts = Counter(r['relationship_type'] for r in relationships)
    uncut = [{'linkId': identifier, 'osmNodeId': node}
             for identifier, interior in feature_interior_nodes.items() for node in sorted(interior)
             if len(node_sources[node]) > 1]
    # Unresolved synthetic cuts are expected. Only source outer endpoints need OSM evidence.
    source_ports = defaultdict(list)
    for f in features:
        source_ports[f['properties'].get('source_link_id') or f['properties']['link_id']].append(f)
    unresolved_source_endpoints = []
    for source, children in source_ports.items():
        children = sorted(children, key=lambda f: f['properties'].get('segment_index', 1))
        for f, side, field in [(children[0], 'start', 'startOsmNodeId'), (children[-1], 'end', 'endOsmNodeId')]:
            if f['properties']['topology'][field] is None:
                unresolved_source_endpoints.append({'sourceLinkId': source, 'linkId': f['properties']['link_id'], 'endpoint': side})
    report = {'valid': not uncut, 'links': len(features), 'relationships': len(relationships),
              'internalRelationships': counts['split_internal'], 'crossSourceRelationships': counts['osm_cross_source'],
              'osmWaysFound': len(index.way_nodes), 'osmNodesLoaded': len(index.coordinates),
              'unknownDirectionLinks': unknown_direction, 'unresolvedSourceEndpoints': unresolved_source_endpoints,
              'uncutSharedJunctions': uncut,
              'linksWithoutIncoming': len(set(ids) - has_incoming), 'linksWithoutOutgoing': len(set(ids) - has_outgoing),
              'pendingLinks': pending,
              'criteria': 'Shared OSM node ID; directed transitions; synthetic endpoints scoped to source; no self U-turn',
              'note': 'Road network connectivity only. OSM turn restrictions and roads outside the selected dataset are not included.'}
    return relationships, report
