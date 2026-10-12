"""Test matching failures that would incorrectly transfer business direction to OSM."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hainan-web/scripts'))
from association.match import Network, associate, business_directions
from visualize_guangdong_amap import convert_coordinates


def road(link_id, coords, oneway='yes'):
    return {'type': 'Feature', 'properties': {'link_id': link_id, 'source_link_id': link_id,
            'highway': 'motorway', 'ref': 'G9811', 'oneway': oneway},
            'geometry': {'type': 'LineString', 'coordinates': coords}}


def api_link(link_id, coords, length, unit_id='unit'):
    start, end = convert_coordinates(coords)
    return {'id': link_id, 'unitId': unit_id, 'startLng': start[0], 'startLat': start[1],
            'endLng': end[0], 'endLat': end[1], 'length': length}


class AssociationTests(unittest.TestCase):
    def setUp(self):
        self.coords = [[110.2, 19.8], [110.2, 19.805]]
        self.north = road('north', self.coords)
        self.south = road('south', [[110.20012, 19.805], [110.20012, 19.8]])
        self.length = Network([self.north]).edges['north']['length']
        self.link = api_link('api', self.coords, self.length)
        self.units = [{'id': 'unit', 'name': '主线收费单元'}]
        self.rels = [{'currentLinkId': 'api', 'nextLinkId': '0', 'direction': 'UP'}]

    def run_match(self, roads, links=None, rels=None, units=None, gates=None):
        return associate(roads, links or [self.link], units or self.units, self.rels if rels is None else rels, gates or [])

    def test_unit_classification_distinguishes_mainline_interval_and_internal_ramps(self):
        from association.grouping import category
        self.assertEqual(category({'name': '屯昌互通—屯昌服务区收费单元'}), 'main')
        self.assertEqual(category({'name': '屯昌服务区收费单元'}), 'service')
        self.assertEqual(category({'name': '侍郎枢纽下行出口分界收费单元'}), 'ramp')

    def test_parallel_reverse_carriageway_cannot_receive_direction(self):
        roads = copy.deepcopy([self.north, self.south])
        mappings, summary = self.run_match(roads)
        self.assertEqual(mappings[0]['status'], 'matched')
        self.assertEqual([m['osmLinkId'] for m in mappings[0]['osmSegments']], ['north'])
        self.assertEqual(roads[0]['properties']['direction_annotation']['code'], 'UP')
        self.assertNotIn('business_association', roads[1]['properties'])
        self.assertEqual(summary['businessDirectionOsmLinks'], 1)

    def test_parallel_same_direction_ambiguity_abstains(self):
        parallel = road('parallel', [[110.20008, 19.8], [110.20008, 19.805]])
        link = api_link('api', [[110.20004, 19.8], [110.20004, 19.805]], self.length)
        mappings, summary = self.run_match([self.north, parallel], [link])
        self.assertEqual(mappings[0]['status'], 'ambiguous')
        self.assertEqual(summary['associatedOsmLinks'], 0)

    def test_one_api_link_can_span_two_osm_links(self):
        middle = [110.2, 19.8025]
        roads = [road('first', [self.coords[0], middle]), road('second', [middle, self.coords[1]])]
        mappings, summary = self.run_match(roads)
        self.assertEqual([s['osmLinkId'] for s in mappings[0]['osmSegments']], ['first', 'second'])
        self.assertEqual(summary['businessDirectionOsmLinks'], 2)

    def test_partial_coverage_retains_original_direction(self):
        self.north['properties']['direction_annotation'] = {'code': None, 'status': 'unconfirmed'}
        link = api_link('api', [[110.2, 19.801], [110.2, 19.804]], self.length * 0.6)
        mappings, summary = self.run_match([self.north], [link])
        self.assertEqual(mappings[0]['status'], 'matched')
        self.assertEqual(summary['businessDirectionOsmLinks'], 0)
        self.assertEqual(self.north['properties']['direction_annotation']['status'], 'unconfirmed')

    def test_length_error_and_bad_gantry_abstain(self):
        wrong = {**self.link, 'length': self.length / 2}
        mappings, _ = self.run_match([self.north], [wrong])
        self.assertEqual(mappings[0]['reason'], 'pathLengthMismatch')
        gate = {'id': 'gate', 'linkId': 'api', 'lng': 111, 'lat': 20}
        mappings, _ = self.run_match([self.north], gates=[gate])
        self.assertEqual(mappings[0]['reason'], 'gantryOutsideMatchedPath')

    def test_conflicting_interface_codes_and_names_do_not_override(self):
        second = {**self.link, 'id': 'api2'}
        rels = self.rels + [{'currentLinkId': 'api2', 'nextLinkId': '0', 'direction': 'DOWN'}]
        roads = copy.deepcopy([self.north])
        _, summary = self.run_match(roads, [self.link, second], rels)
        self.assertEqual(summary['directionConflicts'], 1)
        self.assertNotIn('direction_annotation', roads[0]['properties'])
        roads = copy.deepcopy([self.north])
        _, summary = self.run_match(roads, units=[{'id': 'unit', 'name': '下行主线收费单元'}])
        self.assertEqual(summary['businessDirectionNameConflicts'], 1)
        self.assertNotIn('direction_annotation', roads[0]['properties'])

    def test_relation_direction_is_not_copied_to_terminal_link(self):
        result = business_directions([self.link, {**self.link, 'id': 'terminal'}],
                                    [{'currentLinkId': 'api', 'nextLinkId': 'terminal', 'direction': 'UP'}])
        self.assertEqual(result['api']['code'], 'UP')
        self.assertNotIn('terminal', result)

    def test_reverse_oneway_geometry_is_respected(self):
        reversed_road = road('reverse', list(reversed(self.coords)), oneway='-1')
        mappings, _ = self.run_match([reversed_road])
        self.assertEqual(mappings[0]['status'], 'matched')

    def test_real_snapshot_preserves_geometry_and_ids_and_mapping_references(self):
        raw = ROOT / 'outputs/gis_data/V20260824114228/raw'
        load = lambda name: json.loads((raw / f'{name}.json').read_text())['result']['result']
        roads = json.loads((ROOT / 'outputs/hainan/split/links.geojson').read_text())['features']
        before = copy.deepcopy(roads)
        mappings, summary = associate(roads, load('link'), load('unit'), load('link_relationship'), load('gantry'))
        self.assertGreater(summary['matchedBusinessLinks'], 100)
        self.assertEqual(summary['groups']['routes'], ['G9811'])
        self.assertEqual(len(summary['groups']['mainUnits']), 17)
        self.assertEqual(len(summary['groups']['rampUnits']), 41)
        self.assertTrue(all(check['consistent'] for check in summary['groups']['sequenceChecks']))
        known_components = [c for c in summary['groups']['mainCarriageways'] if c['direction']]
        self.assertEqual({c['direction'] for c in known_components}, {'UP', 'DOWN'})
        self.assertTrue(all(len(c['directionVotes']) == 1 for c in known_components))
        osm_ids = {f['properties']['link_id'] for f in roads}
        for first, last in zip(before, roads):
            self.assertEqual(first['geometry'], last['geometry'])
            self.assertEqual(first['properties'], {k: v for k, v in last['properties'].items() if k not in ('direction_annotation', 'business_association')})
            if last['properties'].get('direction_annotation', {}).get('status') == 'business_matched':
                matches = last['properties']['business_association']['matches']
                self.assertGreaterEqual(last['properties']['business_association']['coverage'], 0.8)
                self.assertEqual(len({m['direction']['code'] for m in matches}), 1)
                self.assertTrue(all(not m['directionNameConflict'] and not m['roadGroup'].get('sequenceReview') for m in matches))
        for m in mappings:
            self.assertTrue(all(segment['osmLinkId'] in osm_ids for segment in m['osmSegments']))
            if m['status'] != 'matched':
                self.assertEqual(m['osmSegments'], [])


if __name__ == '__main__':
    unittest.main()
