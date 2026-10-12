"""Apply local road edits over the immutable OSM source collection."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from link_splitting import MeasuredLine, _to_metric, geometry_to_coordinates


EDIT_SCHEMA = 'hainan-source-edits/v1'
ALLOWED_FIELDS = {'name', 'ref', 'highway', 'oneway', 'lanes', 'maxspeed'}


def empty_edits():
    return {'schema': EDIT_SCHEMA, 'revision': 0, 'nextManualId': 1, 'upserts': {}, 'deleted': []}


def read_edits(path):
    path = Path(path)
    edits = json.loads(path.read_text(encoding='utf-8')) if path.exists() else empty_edits()
    if edits.get('schema') != EDIT_SCHEMA:
        raise ValueError('未知的本地路链编辑记录格式')
    return edits


def effective_sources(collection, edits):
    deleted = set(edits['deleted'])
    upserts = edits['upserts']
    features = []
    seen = set()
    for original in collection['features']:
        source_id = original['properties']['link_id']
        seen.add(source_id)
        if source_id not in deleted:
            features.append(deepcopy(upserts.get(source_id, original)))
    for source_id, feature in upserts.items():
        if source_id not in seen and source_id not in deleted:
            features.append(deepcopy(feature))
    return features


def _coordinates(value):
    if not isinstance(value, list) or not 2 <= len(value) <= 10000:
        raise ValueError('路链至少需要两个、至多 10,000 个 GIS 点')
    points = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('每个 GIS 点必须是 [经度, 纬度]')
        try:
            lon, lat = map(float, point)
        except (ValueError, TypeError) as exc:
            raise ValueError('GIS 坐标必须是数值') from exc
        if not (math.isfinite(lon) and math.isfinite(lat) and 107 <= lon <= 112.5 and 17 <= lat <= 22):
            raise ValueError('请输入海南范围内的 WGS84 经度、纬度')
        if not points or math.hypot(lon - points[-1][0], lat - points[-1][1]) > 1e-12:
            points.append([lon, lat])
    if len(points) < 2:
        raise ValueError('路链至少需要两个不同的 GIS 点')
    MeasuredLine.from_geometry({'type': 'LineString', 'coordinates': points})
    return points


def _properties(value):
    if not isinstance(value, dict) or set(value) - ALLOWED_FIELDS:
        raise ValueError('包含不支持的路链属性')
    result = {}
    for field in ALLOWED_FIELDS:
        if field in value:
            raw = value[field]
            if not isinstance(raw, str) or len(raw) > 120:
                raise ValueError(f'{field} 必须是 120 字以内的文本')
            result[field] = raw.strip()
    if result.get('highway') not in (None, 'motorway', 'motorway_link'):
        raise ValueError('道路类型必须是高速主线或高速匝道')
    if result.get('oneway') not in (None, 'yes', 'no', '-1'):
        raise ValueError('通行方向必须是正向、反向或双向')
    return result


def _nearest_measure(line, point):
    target = _to_metric(tuple(point), line.mode)
    best = (math.inf, 0.0)
    for index, (start, end) in enumerate(zip(line.metric_coordinates, line.metric_coordinates[1:])):
        dx, dy = end[0] - start[0], end[1] - start[1]
        squared_length = dx*dx + dy*dy
        ratio = max(0.0, min(1.0, ((target[0]-start[0])*dx + (target[1]-start[1])*dy)/squared_length)) if squared_length else 0.0
        projected = (start[0]+ratio*dx, start[1]+ratio*dy)
        distance = math.hypot(target[0]-projected[0], target[1]-projected[1])
        candidate = (distance, line.measures[index] + ratio*(line.measures[index+1]-line.measures[index]))
        if candidate < best:
            best = candidate
    return best[1], best[0]


def preferred_cuts(features, previous_roads, only_lineages=None):
    """Project existing child boundaries onto edited sources; reject unrelated roads."""
    by_lineage = {}
    for road in previous_roads:
        p = road['properties']
        lineage = p.get('source_lineage_id') or p.get('osm_source_link_id')
        if lineage:
            by_lineage.setdefault(lineage, []).append(road)
    result = {}
    for source in features:
        p = source['properties']
        source_id = p['link_id']
        lineage = p.get('source_lineage_id') or source_id
        if only_lineages is not None and lineage not in only_lineages:
            continue
        previous = sorted(by_lineage.get(lineage, []), key=lambda item: item['properties'].get('segment_index', 0))
        if len(previous) < 2:
            continue
        line = MeasuredLine.from_geometry(source['geometry'])
        cuts = []
        for child in previous[:-1]:
            point = geometry_to_coordinates(child['geometry'])[-1]
            measure, distance = _nearest_measure(line, point)
            if distance <= 15 and 1 < measure < line.length - 1:
                cuts.append({'measure': measure, 'coordinate': list(point), 'distanceM': distance})
        if cuts:
            result[source_id] = cuts
    return result


def _new_source_id(edits, occupied):
    while True:
        source_id = f"USR_HN_{edits['nextManualId']:06d}"
        edits['nextManualId'] += 1
        if source_id not in occupied:
            return source_id


def _selected(operation, previous_roads):
    link_id = operation.get('linkId')
    selected = next((road for road in previous_roads if road['properties']['link_id'] == link_id), None)
    if selected is None:
        raise ValueError('当前路链已变化，请刷新页面后再编辑')
    source_id = selected['properties'].get('osm_source_link_id')
    if not source_id:
        raise ValueError('当前路链缺少原链标识')
    return selected, source_id


def _segment_range(source, selected):
    line = MeasuredLine.from_geometry(source['geometry'])
    points = geometry_to_coordinates(selected['geometry'])
    start, start_distance = _nearest_measure(line, points[0])
    end, end_distance = _nearest_measure(line, points[-1])
    if start_distance > 0.5 or end_distance > 0.5 or end - start < 0.5:
        raise ValueError('当前路链与原链几何不一致，请先重新生成')
    return line, start, end, points


def apply_edit(collection, old_edits, operation, previous_roads):
    """Return a new overlay; never mutate the source file or committed overlay."""
    if not isinstance(operation, dict):
        raise ValueError('编辑请求格式错误')
    action = operation.get('action')
    if action not in {'add', 'update', 'delete', 'delete_source'}:
        raise ValueError('不支持的路链编辑操作')
    edits = deepcopy(old_edits)
    sources = {f['properties']['link_id']: f for f in effective_sources(collection, edits)}
    if action == 'add':
        source_id = _new_source_id(edits, sources)
        properties = {'link_id': source_id, 'source': '本地编辑', 'coordinate_system': 'EPSG:4326 (WGS84)',
                      'highway': 'motorway', 'oneway': 'yes', 'manual_edit': True}
        properties.update(_properties(operation.get('properties', {})))
        coordinates = _coordinates(operation.get('coordinates'))
        edits['upserts'][source_id] = {'type': 'Feature', 'properties': properties,
                                     'geometry': {'type': 'LineString', 'coordinates': coordinates}}
    else:
        selected, source_id = _selected(operation, previous_roads)
        source = sources.get(source_id)
        if source is None:
            raise ValueError('找不到当前路链的原链')
        if action == 'delete_source':
            edits['upserts'].pop(source_id, None)
            edits['deleted'] = sorted(set([*edits['deleted'], source_id]))
        else:
            line, start, end, old_points = _segment_range(source, selected)
            changed_lineage = source['properties'].get('source_lineage_id') or source_id
            if action == 'update':
                coordinates = _coordinates(operation.get('coordinates'))
                for actual, expected in [(coordinates[0], old_points[0]), (coordinates[-1], old_points[-1])]:
                    if math.hypot(*[a-b for a,b in zip(_to_metric(actual, line.mode), _to_metric(expected, line.mode))]) > 0.5:
                        raise ValueError('编辑当前段时须保留起点和终点，以维持相邻路链连通')
                coordinates[0], coordinates[-1] = list(old_points[0]), list(old_points[-1])
                before = line.slice(0, start)[:-1] if start > 1e-6 else []
                after = line.slice(end, line.length)[1:] if end < line.length - 1e-6 else []
                merged = [*before, *coordinates, *after]
                changed = deepcopy(source)
                changed['geometry'] = {'type': 'LineString', 'coordinates': [list(point) for point in merged]}
                changed['properties'].update(_properties(operation.get('properties', {})))
                changed['properties']['manual_edit'] = True
                MeasuredLine.from_geometry(changed['geometry'])
                edits['upserts'][source_id] = changed
            else:  # delete selected segment, preserving the larger remaining fragment's source identity
                if 1e-6 < start <= 1 or 1e-6 < line.length - end <= 1:
                    raise ValueError('删除会留下不足 1 m 的相邻残段，请先调整该段边界')
                fragments = []
                if start > 1:
                    fragments.append((0, start, line.slice(0, start)))
                if line.length - end > 1:
                    fragments.append((end, line.length, line.slice(end, line.length)))
                if not fragments:
                    edits['upserts'].pop(source_id, None)
                    edits['deleted'] = sorted(set([*edits['deleted'], source_id]))
                else:
                    retained = max(fragments, key=lambda part: part[1]-part[0])
                    for fragment in fragments:
                        target_id = source_id if fragment is retained else _new_source_id(edits, sources)
                        changed = deepcopy(source)
                        changed['properties']['link_id'] = target_id
                        changed['properties']['source_lineage_id'] = source['properties'].get('source_lineage_id') or source_id
                        changed['properties']['manual_edit'] = True
                        changed['geometry'] = {'type': 'LineString', 'coordinates': [list(point) for point in fragment[2]]}
                        edits['upserts'][target_id] = changed
    edits['revision'] += 1
    return edits, changed_lineage if action not in {'add', 'delete_source'} else source_id
