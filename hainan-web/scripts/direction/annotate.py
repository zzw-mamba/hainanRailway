"""Conservative direction annotation from local OSM route membership and directed topology.

Only G98's two nearly complete, unbranched carriageways are inferred UP/DOWN.
These are derived annotations, never source business direction fields.
"""
from collections import Counter, defaultdict
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from inspect_pbf_highways import _fields, _packed_uints, _read_blocks
from extract_motorway_junctions import _tag_map, _packed_signed

G98_RELATION = 909075
EVIDENCE_URL = 'https://www.hainanjk.com/wx/NewsList.aspx?Page=76&cId=23&tx='
OSM_DOC = 'https://wiki.openstreetmap.org/wiki/Relation:route'


def extract_routes(pbf_path):
    routes = []
    for kind, block in _read_blocks(Path(pbf_path)):
        if kind != 'OSMData':
            continue
        strings, groups = [], []
        for number, _, value in _fields(block):
            if number == 1:
                strings = [bytes(item).decode('utf-8', errors='replace') for field, _, item in _fields(value) if field == 1]
            elif number == 2:
                groups.append(value)
        for group in groups:
            for number, _, payload in _fields(group):
                if number != 4:  # PrimitiveGroup.relations
                    continue
                fields = list(_fields(payload))
                tags = _tag_map(fields, strings)
                if tags.get('route') != 'road':
                    continue
                values = {field: value for field, _, value in fields}
                deltas = _packed_signed(values.get(9, memoryview(b'')))
                types = _packed_uints(values.get(10, memoryview(b'')))
                roles = _packed_uints(values.get(8, memoryview(b'')))
                if not len(deltas) == len(types) == len(roles):
                    raise ValueError('OSM route relation member arrays differ in length')
                member_id, members = 0, []
                for delta, kind, role in zip(deltas, types, roles):
                    member_id += delta
                    members.append({'id': member_id, 'type': kind, 'role': strings[role]})
                routes.append({'id': int(values[1]), 'tags': tags, 'members': members})
    return routes


def coordinates(feature):
    geometry = feature['geometry']
    return geometry['coordinates'] if geometry['type'] == 'LineString' else []


def travel_coordinates(feature):
    points = coordinates(feature)
    return list(reversed(points)) if str(feature['properties'].get('oneway')) == '-1' else points


def node_key(point):
    return tuple(round(value, 7) for value in point[:2])


def circulation(features, origin=(109.7, 19.15)):
    total = 0.0
    for feature in features:
        points = travel_coordinates(feature)
        for first, second in zip(points, points[1:]):
            def angle(p):
                return math.atan2(p[1] - origin[1], (p[0] - origin[0]) * math.cos(math.radians(origin[1])))
            total += (angle(second) - angle(first) + math.pi) % (2 * math.pi) - math.pi
    return total


def infer_g98(roads, routes):
    route = next((route for route in routes if route['id'] == G98_RELATION and route['tags'].get('ref') == 'G98'), None)
    if not route:
        return {}, []
    way_ids = {member['id'] for member in route['members'] if member['type'] == 1}
    candidates = [feature for feature in roads if feature['properties'].get('id') in way_ids and feature['properties'].get('highway') == 'motorway' and str(feature['properties'].get('oneway')) in ('yes', '-1') and len(coordinates(feature)) >= 2]
    adjacency, incoming, outgoing = defaultdict(list), Counter(), Counter()
    for index, feature in enumerate(candidates):
        points = travel_coordinates(feature)
        start, end = node_key(points[0]), node_key(points[-1])
        adjacency[start].append(index)
        adjacency[end].append(index)
        outgoing[start] += 1
        incoming[end] += 1
    seen, report, annotations = set(), [], {}
    for index in range(len(candidates)):
        if index in seen:
            continue
        seen.add(index)
        stack, members = [index], []
        while stack:
            current = stack.pop()
            feature = candidates[current]
            members.append(feature)
            points = travel_coordinates(feature)
            for point in (points[0], points[-1]):
                for neighbor in adjacency[node_key(point)]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        keys = {node_key(point) for feature in members for point in (travel_coordinates(feature)[0], travel_coordinates(feature)[-1])}
        angle = circulation(members)
        unbranched = all(len(adjacency[key]) <= 2 and incoming[key] <= 1 and outgoing[key] <= 1 for key in keys)
        # A nearly full circuit allows reliable component propagation through local curves.
        accepted = unbranched and 5.5 <= abs(angle) <= 7.0
        code = ('UP' if angle < 0 else 'DOWN') if accepted else None
        row = {'component': len(report) + 1, 'links': len(members), 'windingRadians': round(angle, 6), 'unbranched': unbranched, 'accepted': accepted, 'inferredDirection': code}
        report.append(row)
        if accepted:
            for feature in members:
                annotations[feature['properties']['link_id']] = {
                    'code': code,
                    'status': 'inferred',
                    'label': '上行（推断）' if code == 'UP' else '下行（推断）',
                    'basis': 'G98路线关系及连续主线拓扑；顺时针推断为上行，逆时针推断为下行。三亚往乐东为上行的公开记录用于校准。',
                    'routeRelationId': G98_RELATION,
                    'component': row['component'],
                }
    # Never accept two components circulating in the same direction as an up/down pair.
    accepted_rows = [row for row in report if row['accepted']]
    if len(accepted_rows) != 2 or {row['inferredDirection'] for row in accepted_rows} != {'UP', 'DOWN'}:
        return {}, [{**row, 'accepted': False, 'inferredDirection': None} for row in report]
    return annotations, report


def annotate(roads, routes):
    inferred, components = infer_g98(roads, routes)
    heading_index = defaultdict(set)
    for route in routes:
        name = route['tags'].get('name', '')
        if '方向' in name:
            for member in route['members']:
                if member['type'] == 1:
                    heading_index[member['id']].add(name)
    for feature in roads:
        props = feature['properties']
        annotation = inferred.get(props['link_id'])
        if annotation is None:
            bidirectional = str(props.get('oneway')) == 'no'
            reason = '双向路链不能赋予单一上下行标签。' if bidirectional else '该路线缺少已核对的上下行基准。'
            if props.get('highway') == 'motorway_link' and not bidirectional:
                reason = '匝道需结合接入主线及出入属性确定上下行，暂不推断。'
            annotation = {'code': None, 'status': 'bidirectional' if bidirectional else 'unconfirmed', 'label': '双向（上下行未区分）' if bidirectional else '上下行待确认', 'basis': reason}
        headings = sorted(heading_index.get(props.get('id'), set()))
        if headings:
            annotation = {**annotation, 'osmRouteHeadings': headings}
        props['direction_annotation'] = annotation
    return {
        'inferredUp': sum(feature['properties']['direction_annotation']['code'] == 'UP' for feature in roads),
        'inferredDown': sum(feature['properties']['direction_annotation']['code'] == 'DOWN' for feature in roads),
        'unconfirmed': sum(feature['properties']['direction_annotation']['status'] == 'unconfirmed' for feature in roads),
        'bidirectional': sum(feature['properties']['direction_annotation']['status'] == 'bidirectional' for feature in roads),
        'components': components,
        'sources': [{'title': '海南交通集团：G98 K294+038（三亚往乐东）上行记录', 'url': EVIDENCE_URL}, {'title': 'OSM 路线关系字段定义', 'url': OSM_DOC}],
        'note': '上下行标注为派生推断；未使用业务 direction=UP/DOWN 字段。仅覆盖通过拓扑检查的G98环线主线，不能直接套用其他路线或匝道。',
    }
