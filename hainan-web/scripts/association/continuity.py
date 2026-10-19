"""Mark safe mainline gaps between confirmed pilot associations as inferred corridor links."""

from collections import Counter


MAX_BRIDGE_M = 6000


def fill_pilot_continuity(roads, groups, max_bridge_m=MAX_BRIDGE_M):
    by_id = {feature['properties']['link_id']: feature for feature in roads}
    gaps = []
    added = set()
    for component in groups.get('mainCarriageways', []):
        direction = component.get('direction')
        route = component.get('route')
        if direction not in ('UP', 'DOWN') or route != 'G9811':
            continue
        ids = component['linkIds']
        confirmed = [index for index, link_id in enumerate(ids)
                     if by_id.get(link_id, {}).get('properties', {}).get('business_association', {}).get('matches')]
        for left, right in zip(confirmed, confirmed[1:]):
            missing = ids[left + 1:right]
            if not missing:
                continue
            features = [by_id.get(link_id) for link_id in missing]
            if any(feature is None or feature['properties'].get('highway') != 'motorway'
                   or route not in str(feature['properties'].get('ref') or '').split(';')
                   or feature['properties'].get('business_association') for feature in features):
                continue
            length_m = sum(float(feature['properties'].get('length_m') or 0) for feature in features)
            if length_m <= 0 or length_m > max_bridge_m:
                continue
            gap = {'carriageway': component['id'], 'direction': direction, 'route': route,
                   'previousConfirmedLinkId': ids[left], 'nextConfirmedLinkId': ids[right],
                   'linkIds': missing, 'lengthM': round(length_m, 1)}
            gaps.append(gap)
            for feature in features:
                link_id = feature['properties']['link_id']
                if link_id in added:
                    continue
                feature['properties']['pilot_continuity'] = {
                    'status': 'topology_bridge', 'route': route, 'carriageway': component['id'],
                    'direction': direction, 'previousConfirmedLinkId': ids[left],
                    'nextConfirmedLinkId': ids[right],
                    'basis': '同一 G9811 单向主线中，位于两条严格接口关联路链之间的拓扑连续路链；未分配接口路链编号。',
                }
                added.add(link_id)
    return {'gapCount': len(gaps), 'addedLinks': len(added),
            'addedLengthM': round(sum(by_id[link_id]['properties'].get('length_m', 0) for link_id in added), 1),
            'byDirection': dict(Counter(gap['direction'] for gap in gaps)), 'gaps': gaps,
            'note': 'Topology bridges are inferred pilot-corridor display links, not verified API-to-OSM associations.'}
