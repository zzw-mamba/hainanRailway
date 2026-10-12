"""Compare the complete highway corridor first, then each interchange ramp unit."""
from collections import Counter, defaultdict
import re


def route_for(link, network):
    if not hasattr(network, '_route_refs'):
        refs = {ref for edge in network.edges.values() for ref in str(edge['ref'] or '').split(';') if re.fullmatch(r'G\d{1,4}', ref)}
        network._route_refs = sorted(refs, key=len, reverse=True)
    return next((ref for ref in network._route_refs if str(link['id']).startswith(ref)), None)


def category(unit):
    name = unit.get('name', '')
    if any(word in name for word in ('匝道', '入口', '出口')):
        return 'ramp'
    # A mainline interval can end at a service area; only its internal unit is separate.
    return 'service' if '服务区' in name and '—' not in name else 'main'


def main_components(network, route):
    edges = {edge_id: edge for edge_id, edge in network.edges.items()
             if edge['highway'] == 'motorway' and route in str(edge['ref'] or '').split(';')}
    touching = defaultdict(list)
    for edge_id, edge in edges.items():
        touching[edge['start']].append(edge_id)
        touching[edge['end']].append(edge_id)
    seen, components, edge_component, stations = set(), [], {}, {}
    for edge_id in sorted(edges):
        if edge_id in seen:
            continue
        pending, group = [edge_id], []
        seen.add(edge_id)
        while pending:
            current = pending.pop()
            group.append(current)
            for node in (edges[current]['start'], edges[current]['end']):
                for neighbor in touching[node]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        pending.append(neighbor)
        outgoing, incoming = defaultdict(list), Counter()
        for current in group:
            outgoing[edges[current]['start']].append(current)
            incoming[edges[current]['end']] += 1
        starts = [node for node in outgoing if not incoming[node]]
        if len(starts) != 1 or any(len(ids) != 1 for ids in outgoing.values()) or any(n > 1 for n in incoming.values()):
            continue
        node, ordered, length = starts[0], [], 0.0
        component_id = f'{route}:carriageway:{len(components) + 1}'
        while node in outgoing:
            current = outgoing[node][0]
            if current in ordered:
                break
            ordered.append(current)
            edge_component[current] = component_id
            stations[current] = length
            length += edges[current]['length']
            node = edges[current]['end']
        if len(ordered) != len(group):
            continue
        components.append({'id': component_id, 'route': route, 'linkIds': ordered, 'osmLinkIds': [network.edges[i]['osmLinkId'] for i in ordered],
                           'lengthM': round(length, 2), 'startWgs84': edges[ordered[0]]['startWgs84'],
                           'endWgs84': edges[ordered[-1]]['endWgs84'], 'directionVotes': {}, 'direction': None})
    return components, edge_component, stations


def corridor_choices(network, link, edge_component, stations):
    from association.match import point
    a, b = point(link, 'start'), point(link, 'end')
    if not a or not b:
        return []
    choices = {}
    for start in network.snap(a, 'main'):
        for end in network.snap(b, 'main'):
            component = edge_component.get(start['id'])
            if not component or component != edge_component.get(end['id']):
                continue
            first = stations[start['id']] + start['offset']
            last = stations[end['id']] + end['offset']
            if last <= first:
                continue
            score = start['distance'] + end['distance']
            if component not in choices or score < choices[component]['score']:
                choices[component] = {'componentId': component, 'score': score,
                     'fromStationM': round(first, 2), 'toStationM': round(last, 2),
                     'geometricLengthM': round(last - first, 2),
                     'startDistanceM': round(start['distance'], 2), 'endDistanceM': round(end['distance'], 2)}
    return sorted(choices.values(), key=lambda choice: choice['score'])


def build_groups(network, links, units, directions, relationships):
    unit_index = {u['id']: u for u in units}
    routes = {route_for(link, network) for link in links}
    components, edge_component, stations = [], {}, {}
    for route in sorted(routes - {None}):
        group, indexes, offsets = main_components(network, route)
        components.extend(group)
        edge_component.update(indexes)
        stations.update(offsets)
    votes = defaultdict(Counter)
    choices_by_link = {}
    for link in links:
        if category(unit_index.get(link.get('unitId'), {})) != 'main':
            continue
        choices = corridor_choices(network, link, edge_component, stations)
        choices_by_link[link['id']] = choices
        if choices and (len(choices) == 1 or choices[1]['score'] - choices[0]['score'] >= 10):
            code = (directions.get(link['id']) or {}).get('code')
            if code:
                votes[choices[0]['componentId']][code] += 1
    code_by_component = {}
    for component in components:
        count = votes[component['id']]
        component['directionVotes'] = dict(count)
        if count:
            code, number = count.most_common(1)[0]
            if number >= 5 and number / sum(count.values()) >= 0.9:
                component['direction'] = code
                code_by_component[component['id']] = code
    unit_directions = defaultdict(set)
    for link in links:
        if directions.get(link['id']):
            unit_directions[link.get('unitId')].add(directions[link['id']]['code'])
    contexts, main_units, ramp_units, review = {}, [], [], []
    by_unit = defaultdict(list)
    for link in links:
        by_unit[link.get('unitId')].append(link)
    for unit in units:
        children = by_unit[unit['id']]
        kind = category(unit)
        info = {'unitId': unit['id'], 'name': unit.get('name'), 'kind': kind,
                'businessLinkIds': [link['id'] for link in children]}
        if kind == 'main':
            main_units.append(info)
            for link in children:
                code = (directions.get(link['id']) or {}).get('code')
                if not code and len(unit_directions[unit['id']]) == 1:
                    code = next(iter(unit_directions[unit['id']]))
                link_route = route_for(link, network)
                allowed = {edge_id for edge_id, component in edge_component.items() if component.startswith(str(link_route) + ':') and (not code or code_by_component.get(component) in (None, code))}
                if link_route:
                    contexts[link['id']] = {'kind': 'main', 'allowedEdges': allowed, 'route': link_route}
                choices = [choice for choice in choices_by_link.get(link['id'], [])
                           if not code or code_by_component.get(choice['componentId']) == code]
                if choices:
                    review.append({'businessLinkId': link['id'], 'unitId': unit['id'], 'unitName': unit.get('name'),
                                   'direction': code, **{k: v for k, v in choices[0].items() if k != 'score'},
                                   'declaredLengthM': link.get('length'), 'status': 'corridorAlignedPendingLinkChecks'})
        else:
            match = re.match(r'^(.+?(?:互通|枢纽|服务区))', unit.get('name', ''))
            info['interchange'] = match.group(1) if match else unit.get('name')
            ramp_units.append(info)
            # Local bounds come from all links in this specific ramp unit, not an island-wide nearest road.
            from association.match import metric, point
            positions = [metric(p) for link in children for prefix in ['start', 'end'] if (p := point(link, prefix))]
            if not positions:
                allowed = set()
            else:
                west, east = min(p[0] for p in positions) - 150, max(p[0] for p in positions) + 150
                south, north = min(p[1] for p in positions) - 150, max(p[1] for p in positions) + 150
                allowed = {edge_id for edge_id, edge in network.edges.items() if edge['highway'] == 'motorway_link'
                           and any(west <= p[0] <= east and south <= p[1] <= north for p in edge['points'])}
            for link in children:
                contexts[link['id']] = {'kind': 'ramp' if kind == 'ramp' else 'service', 'allowedEdges': allowed,
                                       'interchange': info['interchange']}
    candidates = {row['businessLinkId']: row for row in review}
    sequence_checks = []
    for relation in relationships:
        current, following = candidates.get(relation['currentLinkId']), candidates.get(relation['nextLinkId'])
        if not current or not following:
            continue
        same_component = current['componentId'] == following['componentId']
        gap = following['fromStationM'] - current['toStationM'] if same_component else None
        consistent = same_component and -30 <= gap <= 100
        sequence_checks.append({'currentLinkId': relation['currentLinkId'], 'nextLinkId': relation['nextLinkId'],
                                'consistent': consistent, 'stationGapM': round(gap, 2) if gap is not None else None})
        if not consistent:
            for link_id in [relation['currentLinkId'], relation['nextLinkId']]:
                contexts[link_id]['sequenceReview'] = True
    return contexts, {'routes': sorted(routes - {None}), 'mainCarriageways': components,
                      'mainUnits': main_units, 'rampUnits': ramp_units, 'corridorCandidates': review, 'sequenceChecks': sequence_checks,
                      'workflow': 'whole_highway_then_main_chain_then_each_interchange_ramp_unit'}, edge_component
