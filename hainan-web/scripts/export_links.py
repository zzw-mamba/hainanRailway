"""Export the current web road links as a GIS-friendly GeoJSON file."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'hainan-web/public/data/hainan.json'
TARGET = ROOT / 'outputs/hainan/exports/hainan_links_current.geojson'


def export_links(snapshot):
    previous = defaultdict(set)
    following = defaultdict(set)
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    route_names = defaultdict(Counter)
    named_route_totals = Counter()
    for road in snapshot['roads']:
        properties = road['properties']
        if properties.get('highway') != 'motorway' or not properties.get('ref'):
            continue
        name = (properties.get('name') or '').strip()
        if name:
            named_route_totals[properties['ref']] += 1
            if '高速' in name:
                route_names[properties['ref']][name] += 1
    canonical_names = {}
    for route, names in route_names.items():
        name, count = names.most_common(1)[0]
        if count >= 10 and count / named_route_totals[route] >= 0.95:
            canonical_names[route] = name

    for relation in snapshot.get('relationships', []):
        row = deepcopy(relation)
        for key in ('id', 'junctionNode', 'osmNodeId'):
            row.pop(key, None)
        current, next_link = row['currentLinkId'], row['nextLinkId']
        outgoing[current].append(row)
        if next_link != '0' and next_link != 0:
            following[current].add(next_link)
            previous[next_link].add(current)
            incoming[next_link].append(row)

    features = []
    for road in snapshot['roads']:
        feature = {'type': 'Feature', 'properties': deepcopy(road['properties']),
                   'geometry': deepcopy(road['geometry'])}
        properties = feature['properties']
        for key in ('id', 'osm_link_id', 'osm_source_link_id'):
            properties.pop(key, None)
        if 'topology' in properties:
            for key in ('startNode', 'endNode', 'startOsmNodeId', 'endOsmNodeId'):
                properties['topology'].pop(key, None)
        if 'direction_annotation' in properties:
            properties['direction_annotation'].pop('routeRelationId', None)
        association = properties.get('business_association')
        if association:
            for match in association.get('matches', []):
                match.pop('osmLinkId', None)

        points = feature['geometry']['coordinates']
        properties['gis_point_count'] = len(points)
        properties['gis_points'] = [
            {'index': index, 'longitude': longitude, 'latitude': latitude}
            for index, (longitude, latitude) in enumerate(points, start=1)
        ]
        properties['start_lng'], properties['start_lat'] = points[0]
        properties['end_lng'], properties['end_lat'] = points[-1]
        properties['road_type_label'] = {'motorway': '高速主线', 'motorway_link': '高速匝道'}.get(
            properties.get('highway'), '其他道路')
        properties['direction_label'] = properties.get('direction_annotation', {}).get('label', '上下行待确认')
        own_name = (properties.get('name') or '').strip()
        if '高速' in own_name:
            properties['highway_name'] = own_name
            properties['highway_name_basis'] = '路段名称'
        elif properties.get('ref') in canonical_names:
            properties['highway_name'] = canonical_names[properties['ref']]
            properties['highway_name_basis'] = '同路线主线名称推定'
        else:
            properties['highway_name'] = None
            properties['highway_name_basis'] = '待确认'
        link_id = properties['link_id']
        properties['previous_link_ids'] = sorted(previous[link_id])
        properties['next_link_ids'] = sorted(following[link_id])
        properties['relationships'] = {'incoming': incoming[link_id], 'outgoing': outgoing[link_id]}
        features.append(feature)

    return {'type': 'FeatureCollection', 'name': '海南路链数据',
            'generation': snapshot.get('generation'), 'features': features}


def main():
    snapshot = json.loads(SOURCE.read_text(encoding='utf-8'))
    exported = export_links(snapshot)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open('w', encoding='utf-8') as output:
        json.dump(exported, output, ensure_ascii=False, separators=(',', ':'))
        output.write('\n')
    relation_count = sum(len(feature['properties']['relationships']['outgoing']) for feature in exported['features'])
    print(f"已导出 {len(exported['features']):,} 条路链、内嵌 {relation_count:,} 条连通关系：{TARGET}")


if __name__ == '__main__':
    main()
