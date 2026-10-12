"""Embed existing Hainan output, keeping complete properties and both coordinate systems."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from visualize_guangdong_amap import convert_coordinates
from direction.annotate import extract_routes, annotate
from association.match import associate
from identifiers import assign_ids, SCHEMA
from osm_topology import extract_node_index, build_topology

OUT = Path(__file__).resolve().parents[1] / 'public' / 'data'

def prepare(split_dir=None, output_dir=OUT, identifier_dir=None, report_dir=None, generation=None, node_index=None,
            previous_roads=None):
    if split_dir is None:
        active = ROOT / 'outputs/hainan/generated'
        split_dir = active if (active / 'links.geojson').exists() else ROOT / 'outputs/hainan/split'
    split_dir, output_dir = Path(split_dir), Path(output_dir)
    identifier_dir = Path(identifier_dir or ROOT / 'outputs/identifiers')
    report_dir = Path(report_dir or ROOT / 'outputs/associations')
    output_dir.mkdir(parents=True, exist_ok=True)
    identifier_dir.mkdir(parents=True, exist_ok=True)
    print('正在标注上下行…', flush=True)
    roads = json.loads((split_dir / 'links.geojson').read_text(encoding='utf-8'))
    for feature in roads['features']:
        properties = feature['properties']
        if properties.get('ref') == 'G9811' and properties.get('name') == '海乐高速':
            properties['name'] = '海三高速'
    routes = extract_routes(ROOT / 'data' / 'pbf' / 'hainan-260922.osm.pbf')
    direction_summary = annotate(roads['features'], routes)
    for collection in [roads]:
        collection.pop('crs', None)
        for feature in collection['features']:
            props = feature['properties']
            # Omit empty attributes, retain all populated source attributes.
            feature['properties'] = {key: value for key, value in props.items() if value is not None}
            feature['gcjCoordinates'] = convert_coordinates(feature['geometry']['coordinates'])

    relationships = json.loads((split_dir / 'link_relationships.json').read_text(encoding='utf-8'))
    id_mapping = assign_ids(roads['features'], relationships, identifier_dir / 'link_id_registry.json',
                            previous_features=previous_roads)
    print('正在构建 OSM 跨原链拓扑…', flush=True)
    node_index = node_index or extract_node_index(ROOT / 'data/pbf/hainan-260922.osm.pbf', roads['features'])
    relationships, topology_report = build_topology(roads['features'], node_index)
    (output_dir / 'topology_report.json').write_text(json.dumps(topology_report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (identifier_dir / 'link_id_mapping.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(id_mapping[0]))
        writer.writeheader()
        writer.writerows(id_mapping)
    (identifier_dir / 'link_id_mapping.json').write_text(json.dumps(id_mapping, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    business_data = None
    association_summary = None
    latest_path = ROOT / 'outputs' / 'gis_data' / 'latest.json'
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding='utf-8'))
        # Resolve relative to the project, even when npm runs from hainan-web.
        api_dir = Path(latest['path'])
        if not api_dir.is_absolute():
            api_dir = ROOT / api_dir
        def api_records(name):
            path = api_dir / 'raw' / f'{name}.json'
            return json.loads(path.read_text(encoding='utf-8'))['result']['result'] if path.exists() else []
        business_data = {'version': latest['version'], 'links': api_records('link'),
                         'units': api_records('unit'), 'gantries': api_records('gantry'),
                         'relationships': api_records('link_relationship')}
        mappings, association_summary = associate(roads['features'], business_data['links'], business_data['units'],
                                                  business_data['relationships'], business_data['gantries'])
        association_summary['version'] = business_data['version']
        report_dir.mkdir(parents=True, exist_ok=True)
        for directory in [report_dir, output_dir]:
            (directory / 'association_report.json').write_text(json.dumps(association_summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (report_dir / 'business_osm_mapping.json').write_text(json.dumps(mappings, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        fields = ['businessLinkId', 'unitId', 'unitName', 'status', 'reason', 'linkId', 'osmLinkId', 'fromFraction', 'toFraction', 'overlapM', 'direction', 'directionNameConflict', 'startDistanceM', 'endDistanceM', 'pathLengthM', 'lengthErrorM']
        with (report_dir / 'business_osm_mapping.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for mapping in mappings:
                for segment in mapping['osmSegments'] or [{}]:
                    writer.writerow({**mapping, **segment, 'direction': (mapping['direction'] or {}).get('code', '')})
        groups = association_summary['groups']
        with (report_dir / 'highway_unit_comparison.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            fields = ['route', 'kind', 'unitId', 'name', 'interchange', 'businessLinks', 'matched', 'ambiguous', 'unmatched']
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for unit in groups['mainUnits'] + groups['rampUnits']:
                writer.writerow({**unit, 'route': 'G9811', 'businessLinks': len(unit['businessLinkIds']), **unit['statusCounts']})
        with (report_dir / 'main_corridor_candidates.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            fields = ['businessLinkId', 'unitId', 'unitName', 'componentId', 'direction', 'fromStationM', 'toStationM', 'declaredLengthM', 'geometricLengthM', 'startDistanceM', 'endDistanceM', 'linkCheckStatus', 'linkCheckReason']
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(groups['corridorCandidates'])
        # Keep final direction counts consistent with the displayed annotations.
        final_annotations = [f['properties']['direction_annotation'] for f in roads['features']]
        direction_summary['businessMatchedUp'] = sum(a['status'] == 'business_matched' and a['code'] == 'UP' for a in final_annotations)
        direction_summary['businessMatchedDown'] = sum(a['status'] == 'business_matched' and a['code'] == 'DOWN' for a in final_annotations)
        direction_summary['unconfirmed'] = sum(a['status'] == 'unconfirmed' for a in final_annotations)
        print(f"接口关联：{association_summary['matchedBusinessLinks']} / {association_summary['businessLinks']} 条接口路链 → {association_summary['associatedOsmLinks']} 条 OSM 路链")

    payload = {
        'roads': roads['features'],
        'directionSummary': direction_summary,
        'businessData': business_data,
        'associationSummary': association_summary,
        'relationships': relationships,
        'topologySummary': {key: value for key, value in topology_report.items() if key not in ('pendingLinks', 'unknownDirectionLinks', 'unresolvedSourceEndpoints', 'uncutSharedJunctions')},
        'identifierScheme': SCHEMA,
        'generation': {**roads.get('linkSplit', {}), **roads.get('generation', {}), **(generation or {})},
        'validation': json.loads((split_dir / 'validation_report.json').read_text(encoding='utf-8')),
        'source': 'OpenStreetMap · hainan-260922.osm.pbf',
        'coordinateSystem': 'WGS84; 高德显示使用 GCJ-02',
    }
    (output_dir / 'hainan.json').write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"嵌入 {len(payload['roads']):,} 条路链 / {len(payload['relationships']):,} 条有向关系（跨原链 {topology_report['crossSourceRelationships']:,}）")

    (output_dir / 'direction_report.json').write_text(json.dumps(direction_summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"方向推断：上行 {direction_summary['inferredUp']} / 下行 {direction_summary['inferredDown']} / 待确认 {direction_summary['unconfirmed']} / 双向 {direction_summary['bidirectional']}")

    return payload


if __name__ == '__main__':
    prepare()
