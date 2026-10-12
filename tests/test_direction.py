"""Check abstention, orientation and preservation against the real Hainan snapshot."""
import copy
import json
from pathlib import Path
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hainan-web/scripts"))
from direction.annotate import annotate, extract_routes

ROOT = Path(__file__).resolve().parents[1]


class DirectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roads = json.loads((ROOT / 'outputs/hainan/split/links.geojson').read_text())['features']
        cls.routes = extract_routes(ROOT / 'data/pbf/hainan-260922.osm.pbf')

    def test_real_calibration_and_source_preservation(self):
        roads = copy.deepcopy(self.roads)
        report = annotate(roads, self.routes)
        self.assertEqual((report['inferredUp'], report['inferredDown']), (1671, 1676))
        for before, after in zip(self.roads, roads):
            self.assertEqual(before['geometry'], after['geometry'])
            self.assertEqual(before['properties'], {k: v for k, v in after['properties'].items() if k != 'direction_annotation'})
            if after['properties']['direction_annotation']['code']:
                self.assertEqual(after['properties']['highway'], 'motorway')
                self.assertEqual(after['properties']['direction_annotation']['status'], 'inferred')
        lookup = {f['properties']['link_id']: f for f in roads}
        # East coast at Lingshui: northbound is counterclockwise, inferred DOWN.
        self.assertEqual(lookup['OSM_HN_71216352_0__S001']['properties']['direction_annotation']['code'], 'DOWN')
        # Cross-check the western Sanya–Ledong corridor: UP travels west.
        corridor = [f for f in roads if f['properties']['direction_annotation']['code'] == 'UP' and all(109.0 < p[0] < 109.25 and 18.3 < p[1] < 18.55 for p in f['geometry']['coordinates'])]
        self.assertTrue(corridor)
        self.assertLess(sum(f['geometry']['coordinates'][-1][0] - f['geometry']['coordinates'][0][0] for f in corridor), 0)

    def test_reverse_geometry_with_reverse_oneway_preserves_direction(self):
        roads = copy.deepcopy(self.roads)
        baseline = annotate(roads, self.routes)
        for f in roads:
            if f['properties']['direction_annotation']['code']:
                f['geometry']['coordinates'].reverse()
                f['properties']['oneway'] = '-1'
        report = annotate(roads, self.routes)
        self.assertEqual(report['inferredUp'], baseline['inferredUp'])
        self.assertEqual(report['inferredDown'], baseline['inferredDown'])

    def test_direction_break_abstains_instead_of_propagating(self):
        roads = copy.deepcopy(self.roads)
        roads[0]['geometry']['coordinates'].reverse()  # Traffic direction now contradicts neighbors.
        report = annotate(roads, self.routes)
        self.assertEqual(report['inferredUp'] + report['inferredDown'], 0)

    def test_missing_relation_and_ramps_are_not_assigned_up_down(self):
        roads = copy.deepcopy(self.roads)
        report = annotate(roads, [])
        self.assertEqual(report['inferredUp'] + report['inferredDown'], 0)
        self.assertEqual(report['bidirectional'], 79)
        self.assertTrue(all(f['properties']['direction_annotation']['code'] is None for f in roads))


if __name__ == '__main__':
    unittest.main()
