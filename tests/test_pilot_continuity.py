"""Pilot corridor infill must remain distinct from confirmed interface mappings."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hainan-web/scripts'))
from association.continuity import fill_pilot_continuity


def road(link_id, matched=False, length=400, route='G9811'):
    properties = {'link_id': link_id, 'highway': 'motorway', 'ref': route, 'length_m': length}
    if matched:
        properties['business_association'] = {'matches': [{'businessLinkId': link_id}]}
    return {'properties': properties}


class PilotContinuityTests(unittest.TestCase):
    def test_only_internal_same_carriageway_gaps_are_inferred(self):
        roads = [road('outside-before'), road('matched-a', True), road('middle'),
                 road('matched-b', True), road('outside-after')]
        groups = {'mainCarriageways': [{'id': 'G9811:carriageway:1', 'route': 'G9811',
                  'direction': 'UP', 'linkIds': [row['properties']['link_id'] for row in roads]}]}
        report = fill_pilot_continuity(roads, groups)
        self.assertEqual(report['addedLinks'], 1)
        self.assertEqual(report['gapCount'], 1)
        self.assertEqual(roads[2]['properties']['pilot_continuity']['previousConfirmedLinkId'], 'matched-a')
        self.assertEqual(roads[2]['properties']['pilot_continuity']['nextConfirmedLinkId'], 'matched-b')
        self.assertNotIn('business_association', roads[2]['properties'])
        self.assertNotIn('pilot_continuity', roads[0]['properties'])
        self.assertNotIn('pilot_continuity', roads[-1]['properties'])

    def test_wrong_route_or_long_gap_is_not_filled(self):
        roads = [road('a', True), road('wrong-route', route='G98'), road('b', True),
                 road('long', length=7000), road('c', True)]
        groups = {'mainCarriageways': [{'id': 'G9811:carriageway:1', 'route': 'G9811',
                  'direction': 'DOWN', 'linkIds': [row['properties']['link_id'] for row in roads]}]}
        report = fill_pilot_continuity(roads, groups)
        self.assertEqual(report['addedLinks'], 0)

    def test_real_snapshot_fills_confirmed_mainline_gaps_without_api_ids(self):
        payload = json.loads((ROOT / 'hainan-web/public/data/hainan.json').read_text())
        report = fill_pilot_continuity(payload['roads'], payload['associationSummary']['groups'])
        self.assertEqual(report['gapCount'], 22)
        self.assertEqual(report['addedLinks'], 112)
        self.assertAlmostEqual(report['addedLengthM'] / 1000, 52.5, delta=0.1)
        inferred = [f for f in payload['roads'] if f['properties'].get('pilot_continuity')]
        self.assertTrue(all(not f['properties'].get('business_association') for f in inferred))
        by_id = {f['properties']['link_id']: f['properties'] for f in payload['roads']}
        for component in payload['associationSummary']['groups']['mainCarriageways']:
            if component.get('direction') not in ('UP', 'DOWN'):
                continue
            ids = component['linkIds']
            confirmed = [index for index, link_id in enumerate(ids)
                         if by_id[link_id].get('business_association')]
            if len(confirmed) < 2:
                continue
            self.assertTrue(all(by_id[link_id].get('business_association') or
                                by_id[link_id].get('pilot_continuity')
                                for link_id in ids[confirmed[0]:confirmed[-1] + 1]))


if __name__ == '__main__':
    unittest.main()
