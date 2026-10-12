"""Stable project IDs backed by a persistent registry; source IDs remain provenance."""
from collections import defaultdict
import json
import hashlib
from pathlib import Path
import re

SCHEMA = 'HN-ROUTE-TYPE-SEQUENCE/v1'


def route_token(value):
    tokens = sorted({part.strip().upper() for part in str(value or '').split(';') if part.strip()})
    if not tokens:
        return 'UN'
    if not all(re.fullmatch(r'[A-Z][A-Z0-9]*', token) for token in tokens):
        raise ValueError(f'Unsupported route token: {value!r}')
    return '+'.join(tokens)


def road_kind(properties):
    return 'M' if properties.get('highway') == 'motorway' else 'R' if properties.get('highway') == 'motorway_link' else 'O'


def position_key(feature):
    def positions(coords):
        if len(coords) >= 2 and isinstance(coords[0], (int, float)):
            yield coords
        else:
            for child in coords:
                yield from positions(child)
    points = list(positions(feature['geometry']['coordinates']))
    return (round(min(p[1] for p in points), 7), round(min(p[0] for p in points), 7))


def geometry_key(feature):
    """Stable identity for an unchanged child even if deletion shifts its ordinal."""
    p = feature['properties']
    lineage = p.get('source_lineage_id') or p.get('osm_source_link_id') or p.get('source_link_id')
    def rounded(value):
        if isinstance(value, (list, tuple)):
            return [rounded(child) for child in value]
        return round(value, 9)
    shape = json.dumps(rounded(feature['geometry']['coordinates']), separators=(',', ':'))
    return f"{lineage}:{hashlib.sha256(shape.encode()).hexdigest()}"


def assign_ids(features, relationships, registry_path, previous_features=None):
    """Assign IDs in place, migrate references, and return a complete provenance table."""
    registry_path = Path(registry_path)
    registry = json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {
        'schema': SCHEMA, 'links': {}, 'sources': {}, 'nextSequence': {}, 'nextSourceSequence': 1}
    if registry.get('schema') != SCHEMA:
        raise ValueError('Unknown link ID registry schema')
    link_registry, source_registry = registry['links'], registry['sources']
    existing = list(link_registry.values()) + list(source_registry.values())
    if len(existing) != len(set(existing)):
        raise ValueError('Registry contains duplicate allocated IDs')
    geometries = registry.setdefault('geometries', {})
    geometry_ids = registry.setdefault('geometryIds', {})
    reserved_ids = set(link_registry.values())
    for previous in previous_features or []:
        old_id = previous['properties'].get('link_id')
        if old_id in reserved_ids:
            geometry_ids.setdefault(geometry_key(previous), old_id)
    def identity(feature):
        p = feature['properties']
        original = p.get('osm_link_id', p['link_id'])
        fingerprint = hashlib.sha256(json.dumps(feature['geometry'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if original not in geometries:
            geometries[original] = fingerprint
        return original if geometries[original] == fingerprint else f'{original}@{fingerprint}'
    identity_keys = {id(feature): identity(feature) for feature in features}
    originals = [f['properties'].get('osm_link_id', f['properties']['link_id']) for f in features]
    if len(originals) != len(set(originals)):
        raise ValueError('Input contains duplicate link IDs')
    by_source = defaultdict(list)
    for feature in features:
        p = feature['properties']
        by_source[p.get('osm_source_link_id', p['source_link_id'])].append(feature)
    for original in sorted(by_source, key=lambda key: (min(position_key(f) for f in by_source[key]), key)):
        if original not in source_registry:
            number = registry['nextSourceSequence']
            if number > 999999:
                raise ValueError('Source ID sequence exhausted')
            source_registry[original] = f'HN-SRC-{number:06d}'
            registry['nextSourceSequence'] = number + 1
    def allocation_key(feature):
        p = feature['properties']
        return (route_token(p.get('ref')), road_kind(p), *position_key(feature), p.get('osm_link_id', p['link_id']))
    assigned = {}
    for feature in sorted(features, key=allocation_key):
        p = feature['properties']
        original = p.get('osm_link_id', p['link_id'])
        key = identity_keys[id(feature)]
        prefix = f"HN-{route_token(p.get('ref'))}-{road_kind(p)}"
        if key in link_registry and not link_registry[key].startswith(prefix + '-'):
            key = f'{key}@{prefix}'
        reusable = geometry_ids.get(geometry_key(feature))
        if key in link_registry:
            assigned[id(feature)] = link_registry[key]
        elif reusable in reserved_ids and reusable.startswith(prefix + '-'):
            assigned[id(feature)] = reusable
        else:
            number = registry['nextSequence'].get(prefix, 1)
            if number > 999999:
                raise ValueError(f'Link ID sequence exhausted: {prefix}')
            link_registry[key] = f'{prefix}-{number:06d}'
            registry['nextSequence'][prefix] = number + 1
            reserved_ids.add(link_registry[key])
            assigned[id(feature)] = link_registry[key]
        geometry_ids.setdefault(geometry_key(feature), assigned[id(feature)])
    if len(assigned.values()) != len(set(assigned.values())):
        raise ValueError('Two current road geometries would reuse one project ID')
    allocated = list(link_registry.values()) + list(source_registry.values())
    if len(allocated) != len(set(allocated)):
        raise ValueError('Registry counter would reuse an existing ID')
    current_ids = {p['properties']['link_id']: assigned[id(p)] for p in features}
    current_sources = {p['properties']['source_link_id']: source_registry[p['properties'].get('osm_source_link_id', p['properties']['source_link_id'])] for p in features}
    migrated = []
    for relation in relationships:
        row = dict(relation)
        for field in ['currentLinkId', 'nextLinkId']:
            value = str(row[field])
            if field == 'nextLinkId' and value == '0':
                continue
            if value not in current_ids:
                raise ValueError(f'Dangling relationship reference: {value}')
            row[field] = current_ids[value]
        if row.get('source_link_id'):
            if row['source_link_id'] not in current_sources:
                raise ValueError('Dangling relationship source reference')
            row['source_link_id'] = current_sources[row['source_link_id']]
        migrated.append(row)
    mapping = []
    for feature in features:
        p = feature['properties']
        original, original_source = p.get('osm_link_id', p['link_id']), p.get('osm_source_link_id', p['source_link_id'])
        p.update({'link_id': assigned[id(feature)], 'source_link_id': source_registry[original_source],
                  'osm_link_id': original, 'osm_source_link_id': original_source})
        mapping.append({'linkId': p['link_id'], 'sourceLinkId': p['source_link_id'],
                        'osmLinkId': original, 'osmSourceLinkId': original_source, 'osmWayId': p.get('id'),
                        'ref': p.get('ref', ''), 'highway': p.get('highway'), 'segmentIndex': p.get('segment_index')})
    relationships[:] = migrated
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temp = registry_path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(registry_path)
    return sorted(mapping, key=lambda row: row['linkId'])
