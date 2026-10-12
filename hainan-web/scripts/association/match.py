"""Conservative directed path association; API IDs never replace OSM identities."""
from collections import defaultdict, Counter
import heapq
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from visualize_guangdong_amap import convert_coordinates

X_SCALE = 111320 * math.cos(math.radians(19.8))
Y_SCALE = 111320
CELL = 100.0
MAX_SNAP = 20.0


def metric(point):
    return ((point[0] - 110) * X_SCALE, (point[1] - 19.8) * Y_SCALE)


def key(point):
    return tuple(round(value, 7) for value in point[:2])


def distance(first, second):
    return math.hypot(first[0] - second[0], first[1] - second[1])


class Network:
    def __init__(self, roads, coordinate_system='GCJ02'):
        self.edges = {}
        self.adjacency = defaultdict(list)
        self.grid = defaultdict(list)
        for feature in roads:
            props, geom = feature['properties'], feature['geometry']
            if geom['type'] != 'LineString' or str(props.get('oneway')) not in ('yes', '-1'):
                continue
            coords = geom['coordinates']
            if str(props.get('oneway')) == '-1':
                coords = list(reversed(coords))
            transformed = convert_coordinates(coords) if coordinate_system == 'GCJ02' else coords
            points = [metric(point) for point in transformed]
            length = sum(distance(a, b) for a, b in zip(points, points[1:]))
            if length <= 0:
                continue
            link_id = props['link_id']
            topology = props.get('topology', {})
            start_node, end_node = topology.get('startNode'), topology.get('endNode')
            if str(props.get('oneway')) == '-1':
                start_node, end_node = end_node, start_node
            edge = {'id': link_id, 'start': start_node or key(coords[0]), 'end': end_node or key(coords[-1]),
                    'startWgs84': list(coords[0]), 'endWgs84': list(coords[-1]),
                    'points': points, 'length': length, 'highway': props.get('highway'),
                    'osmLinkId': props.get('osm_link_id', link_id),
                    'ref': props.get('ref'), 'sourceLinkId': props.get('source_link_id')}
            self.edges[link_id] = edge
            self.adjacency[edge['start']].append(link_id)
            offset = 0.0
            for first, second in zip(points, points[1:]):
                segment_length = distance(first, second)
                if not segment_length:
                    continue
                segment = (link_id, first, second, offset, segment_length)
                for x in range(math.floor(min(first[0], second[0]) / CELL), math.floor(max(first[0], second[0]) / CELL) + 1):
                    for y in range(math.floor(min(first[1], second[1]) / CELL), math.floor(max(first[1], second[1]) / CELL) + 1):
                        self.grid[x, y].append(segment)
                offset += segment_length

    def allowed(self, edge, kind):
        return edge['highway'] == 'motorway_link' if kind == 'ramp' else edge['highway'] == 'motorway' and 'G9811' in str(edge['ref']).split(';')

    def snap(self, point, kind=None, radius=MAX_SNAP):
        p = metric(point)
        found, visited = {}, set()
        for x in range(math.floor((p[0] - radius) / CELL), math.floor((p[0] + radius) / CELL) + 1):
            for y in range(math.floor((p[1] - radius) / CELL), math.floor((p[1] + radius) / CELL) + 1):
                for link_id, a, b, offset, segment_length in self.grid[x, y]:
                    segment_key = (link_id, offset)
                    if segment_key in visited:
                        continue
                    visited.add(segment_key)
                    edge = self.edges[link_id]
                    if kind and not self.allowed(edge, kind):
                        continue
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / segment_length ** 2))
                    d = distance(p, (a[0] + t * dx, a[1] + t * dy))
                    if d <= radius and (link_id not in found or d < found[link_id]['distance']):
                        found[link_id] = {'id': link_id, 'offset': offset + t * segment_length, 'distance': d}
        return sorted(found.values(), key=lambda row: (row['distance'], row['id']))[:8]

    def path(self, start, end, kind, maximum):
        first, last = self.edges[start['id']], self.edges[end['id']]
        if first['id'] == last['id'] and end['offset'] >= start['offset']:
            return [(first['id'], start['offset'], end['offset'])]
        initial = first['length'] - start['offset']
        pending = [(initial, first['end'], [])]
        best = {first['end']: initial}
        while pending:
            cost, node, middle = heapq.heappop(pending)
            if cost > maximum or cost > best[node]:
                continue
            if node == last['start']:
                return [(first['id'], start['offset'], first['length']), *middle, (last['id'], 0, end['offset'])]
            for edge_id in self.adjacency.get(node, []):
                edge = self.edges[edge_id]
                if not self.allowed(edge, kind) or edge_id in (first['id'], last['id']):
                    continue
                new_cost = cost + edge['length']
                if new_cost < best.get(edge['end'], math.inf) and new_cost <= maximum:
                    best[edge['end']] = new_cost
                    heapq.heappush(pending, (new_cost, edge['end'], [*middle, (edge_id, 0, edge['length'])]))
        return None


def similarity(first, second):
    """Overlap of directed path intervals; adjacent split endpoints are equivalent."""
    def intervals(path):
        result = defaultdict(list)
        for edge_id, start, end in path:
            if end > start:
                result[edge_id].append((start, end))
        return result
    a, b = intervals(first), intervals(second)
    common = sum(max(0, min(a1, b1) - max(a0, b0)) for edge_id in a.keys() & b.keys() for a0, a1 in a[edge_id] for b0, b1 in b[edge_id])
    total_a = sum(end - start for _, start, end in first)
    total_b = sum(end - start for _, start, end in second)
    return common / max(total_a, total_b, 1)


def point(record, prefix):
    try:
        lng, lat = float(record[prefix + 'Lng']), float(record[prefix + 'Lat'])
        return [lng, lat] if 108 < lng < 112 and 18 < lat < 21 else None
    except (KeyError, TypeError, ValueError):
        return None


def business_directions(links, relationships):
    """Only currentLinkId owns the direction; never copy it to nextLinkId."""
    direct = defaultdict(set)
    for row in relationships:
        if row.get('direction') in ('UP', 'DOWN'):
            direct[row['currentLinkId']].add(row['direction'])
    return {link['id']: {'code': next(iter(direct[link['id']])), 'source': 'currentLinkId'}
            for link in links if len(direct[link['id']]) == 1}


def match_link(network, link, unit, gantries, context=None):
    result = {'businessLinkId': link['id'], 'unitId': link.get('unitId'), 'unitName': unit.get('name', ''),
              'status': 'unmatched', 'osmSegments': []}
    start_point, end_point = point(link, 'start'), point(link, 'end')
    length = float(link.get('length') or 0)
    result['startStakeNum'] = link.get('startStakeNum', '')
    result['endStakeNum'] = link.get('endStakeNum', '')
    if not start_point or not end_point or length <= 0:
        result['reason'] = 'invalidEndpointOrLength'
        return result
    # Service area units may include multiple OSM classes; abstain rather than guess.
    kind = (context or {}).get('kind') or ('ramp' if '匝道' in unit.get('name', '') else 'main')
    if kind == 'service':
        result['reason'] = 'serviceAreaNeedsSeparateReview'
        return result
    starts, ends = network.snap(start_point, kind), network.snap(end_point, kind)
    if context is not None:
        starts = [snap for snap in starts if snap['id'] in context['allowedEdges']]
        ends = [snap for snap in ends if snap['id'] in context['allowedEdges']]
    if not starts or not ends:
        result['reason'] = 'endpointOutsideTolerance'
        return result
    candidates = []
    had_path = had_valid_length = False
    for start in starts:
        for end in ends:
            path = network.path(start, end, kind, length * 1.25 + 40)
            if not path:
                continue
            if context is not None and any(edge_id not in context['allowedEdges'] for edge_id, _, _ in path):
                continue
            had_path = True
            path = [part for part in path if part[2] - part[1] > 0.1]
            path_length = sum(last - first for _, first, last in path)
            error = abs(path_length - length)
            if error > max(30, length * 0.15) or not path:
                continue
            had_valid_length = True
            # Reject paths missing any same-link gantry within 20 m. Bad gantry positions cause abstention.
            gate_errors = []
            for gate in gantries:
                snaps = network.snap([float(gate['lng']), float(gate['lat'])], kind)
                distances = [s['distance'] for s in snaps for edge_id, first, last in path if edge_id == s['id'] and first - 5 <= s['offset'] <= last + 5]
                gate_errors.append(min(distances, default=math.inf))
            if any(error > MAX_SNAP for error in gate_errors):
                continue
            score = start['distance'] + end['distance'] + error * 0.1
            candidates.append({'path': path, 'score': score, 'pathLengthM': path_length, 'lengthErrorM': error,
                               'startDistanceM': start['distance'], 'endDistanceM': end['distance'],
                               'gantryDistancesM': gate_errors})
    if not candidates:
        result['reason'] = 'gantryOutsideMatchedPath' if had_valid_length else 'pathLengthMismatch' if had_path else 'noDirectedPath'
        return result
    candidates.sort(key=lambda row: row['score'])
    best = candidates[0]
    alternatives = [row for row in candidates[1:] if similarity(row['path'], best['path']) < 0.8]
    if alternatives and alternatives[0]['score'] - best['score'] < 10:
        result['status'] = 'ambiguous'
        result['reason'] = 'similarAlternativePath'
        result['candidateCount'] = len(alternatives) + 1
        return result
    result.update({k: round(v, 2) if isinstance(v, float) else v for k, v in best.items() if k not in ('path', 'score')})
    result['status'] = 'matched'
    result['reason'] = 'directedSpatialPath'
    result['osmSegments'] = [{'linkId': edge_id, 'osmLinkId': network.edges[edge_id]['osmLinkId'], 'fromFraction': round(first / network.edges[edge_id]['length'], 6),
                              'toFraction': round(last / network.edges[edge_id]['length'], 6),
                              'overlapM': round(last - first, 2)} for edge_id, first, last in best['path']]
    return result


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def coordinate_assessment(roads, links, gantries):
    samples = [point(link, prefix) for link in links for prefix in ['start', 'end']]
    samples = [p for p in samples if p]
    gate_points = [[float(g['lng']), float(g['lat'])] for g in gantries]
    assessment = {}
    for system in ['WGS84', 'GCJ02']:
        network = Network(roads, system)
        def statistics(points):
            ds = [snaps[0]['distance'] for p in points if (snaps := network.snap(p, radius=1000))]
            ds.sort()
            return {'samples': len(points), 'within1km': len(ds),
                    'medianM': round((ds[(len(ds)-1)//2] + ds[len(ds)//2]) / 2, 2) if ds else None,
                    'p90M': round(ds[min(len(ds)-1, math.ceil(len(ds)*0.9)-1)], 2) if ds else None,
                    'within20m': sum(d <= 20 for d in ds)}
        assessment[system] = {'linkEndpoints': statistics(samples), 'gantries': statistics(gate_points)}
    assessment['note'] = 'GCJ-02 is a spatial hypothesis for API links/units; only gantries are provider-documented GCJ-02.'
    return assessment


def associate(roads, links, units, relationships, gantries):
    network = Network(roads)
    unit_index = {row['id']: row for row in units}
    gate_index = defaultdict(list)
    for row in gantries:
        gate_index[row['linkId']].append(row)
    directions = business_directions(links, relationships)
    from association.grouping import build_groups
    contexts, groups, edge_component = build_groups(network, links, units, directions, relationships)
    mappings = [match_link(network, link, unit_index.get(link.get('unitId'), {}), gate_index[link['id']], contexts.get(link['id'])) for link in links]
    by_business = {m['businessLinkId']: m for m in mappings}
    for candidate in groups['corridorCandidates']:
        candidate['linkCheckStatus'] = by_business[candidate['businessLinkId']]['status']
        candidate['linkCheckReason'] = by_business[candidate['businessLinkId']]['reason']
    for unit in groups['mainUnits'] + groups['rampUnits']:
        unit['statusCounts'] = dict(Counter(by_business[link_id]['status'] for link_id in unit['businessLinkIds']))
    osm_index = defaultdict(list)
    for mapping in mappings:
        mapping['roadGroup'] = {k: v for k, v in contexts.get(mapping['businessLinkId'], {}).items() if k != 'allowedEdges'}
        mapping['direction'] = directions.get(mapping['businessLinkId'])
        named_direction = 'UP' if '上行' in mapping['unitName'] else 'DOWN' if '下行' in mapping['unitName'] else None
        mapping['directionNameConflict'] = bool(named_direction and mapping['direction'] and named_direction != mapping['direction']['code'])
        mapping['gantryIds'] = [g['id'] for g in gate_index[mapping['businessLinkId']]]
        for segment in mapping['osmSegments']:
            osm_index[segment['linkId']].append({**segment, 'businessLinkId': mapping['businessLinkId'],
                  'unitId': mapping['unitId'], 'unitName': mapping['unitName'], 'roadGroup': mapping['roadGroup'], 'direction': mapping['direction'],
                  'directionNameConflict': mapping['directionNameConflict'], 'startStakeNum': mapping['startStakeNum'], 'endStakeNum': mapping['endStakeNum'],
                  'gantryIds': mapping['gantryIds'], 'startDistanceM': mapping['startDistanceM'], 'endDistanceM': mapping['endDistanceM']})
    annotated = 0
    conflicts = 0
    partial = 0
    for feature in roads:
        matches = osm_index.get(feature['properties']['link_id'], [])
        if not matches:
            continue
        intervals = merge_intervals((match['fromFraction'], match['toFraction']) for match in matches)
        coverage = sum(end - start for start, end in intervals)
        codes = {match['direction']['code'] for match in matches if match['direction']}
        association = {'status': 'spatially_matched', 'coverage': round(coverage, 4), 'matches': matches,
                       'coordinateHypothesis': 'API as GCJ-02; spatially supported, not provider confirmed'}
        feature['properties']['business_association'] = association
        if coverage >= 0.8 and len(codes) == 1 and all(match['direction'] and not match['directionNameConflict'] and not match['roadGroup'].get('sequenceReview') for match in matches):
            code = next(iter(codes))
            feature['properties']['direction_annotation'] = {'code': code, 'status': 'business_matched',
                'label': ('上行' if code == 'UP' else '下行') + '（接口空间关联）',
                'basis': '方向值来自 BDS_LINKREL_LIST；接口路链通过 GCJ-02 坐标假设、单向道路拓扑、长度及门架检查关联到 OSM，属于空间匹配结果。',
                'businessLinkIds': [match['businessLinkId'] for match in matches]}
            annotated += 1
        else:
            if len(codes) > 1 or any(match['directionNameConflict'] or match['roadGroup'].get('sequenceReview') for match in matches):
                association['directionStatus'] = 'conflict'
                conflicts += 1
            else:
                association['directionStatus'] = 'partialOrMissing'
                partial += 1
    statuses = dict(Counter(mapping['status'] for mapping in mappings))
    summary = {'coordinateAssessment': coordinate_assessment(roads, links, gantries), 'groups': groups, 'businessLinks': len(links), 'businessRelationships': len(relationships), 'matchedBusinessLinks': statuses.get('matched', 0),
        'ambiguousBusinessLinks': statuses.get('ambiguous', 0), 'unmatchedBusinessLinks': statuses.get('unmatched', 0),
        'associatedOsmLinks': len(osm_index), 'businessDirectionOsmLinks': annotated, 'directionConflicts': conflicts,
        'partialOrMissingDirectionOsmLinks': partial,
        'matchedGantries': sum(len(m['gantryIds']) for m in mappings if m['status'] == 'matched'),
        'businessDirectionNameConflicts': sum(m['directionNameConflict'] for m in mappings),
        'unmatchedReasons': dict(Counter(m.get('reason') for m in mappings if m['status'] != 'matched')),
        'criteria': {'coordinateHypothesis': 'GCJ-02', 'maxEndpointDistanceM': MAX_SNAP,
                     'lengthTolerance': 'max(30 m, 15%)', 'minimumOsmDirectionCoverage': 0.8,
                     'ambiguousScoreMargin': 10, 'scope': 'G9811 mainline and named ramps'},
        'note': 'No shared IDs. Many-to-many spatial association only. API coordinate reference for links is not provider-confirmed. Unmatched and ambiguous links are not assigned.'}
    return mappings, summary
