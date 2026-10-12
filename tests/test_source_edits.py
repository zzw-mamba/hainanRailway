"""Selected-child editing keeps the underlying OSM collection untouched."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hainan-web/scripts'))
from source_edits import apply_edit, effective_sources, empty_edits, preferred_cuts


def road(source_id, coordinates, **extra):
    return {'type': 'Feature', 'properties': {'link_id': source_id, 'highway': 'motorway',
            'ref': 'G98', 'oneway': 'yes', **extra},
            'geometry': {'type': 'LineString', 'coordinates': coordinates}}


class SourceEditTests(unittest.TestCase):
    def setUp(self):
        self.points = [[110, 19], [110.005, 19], [110.01, 19], [110.015, 19]]
        self.collection = {'type': 'FeatureCollection', 'features': [road('OSM-1', self.points)]}
        self.original = copy.deepcopy(self.collection)
        self.children = [road(f'HN-G98-M-{i:06d}', self.points[i-1:i+1],
                              osm_source_link_id='OSM-1', segment_index=i)
                         for i in range(1, 4)]

    def test_add_creates_overlay_without_mutating_source(self):
        edits, lineage = apply_edit(self.collection, empty_edits(), {'action': 'add',
            'properties': {'name': '测试路段', 'highway': 'motorway_link'},
            'coordinates': [[110.02, 19], [110.021, 19]]}, self.children)
        self.assertEqual(lineage, 'USR_HN_000001')
        self.assertEqual(edits['revision'], 1)
        self.assertEqual(len(effective_sources(self.collection, edits)), 2)
        self.assertEqual(self.collection, self.original)

    def test_update_replaces_only_selected_geometry(self):
        edits, lineage = apply_edit(self.collection, empty_edits(), {'action': 'update',
            'linkId': self.children[1]['properties']['link_id'],
            'properties': {'name': '更新主线'},
            'coordinates': [self.points[1], [110.007, 19.001], self.points[2]]}, self.children)
        changed = effective_sources(self.collection, edits)[0]
        self.assertEqual(lineage, 'OSM-1')
        self.assertEqual(changed['geometry']['coordinates'],
                         [self.points[0], self.points[1], [110.007, 19.001], self.points[2], self.points[3]])
        self.assertEqual(changed['properties']['name'], '更新主线')
        self.assertEqual(self.collection, self.original)
        with self.assertRaisesRegex(ValueError, '起点和终点'):
            apply_edit(self.collection, empty_edits(), {'action': 'update',
                'linkId': self.children[1]['properties']['link_id'],
                'coordinates': [[110.006, 19], self.points[2]]}, self.children)

    def test_delete_removes_only_selected_child_and_retains_both_sides(self):
        edits, lineage = apply_edit(self.collection, empty_edits(), {'action': 'delete',
            'linkId': self.children[1]['properties']['link_id']}, self.children)
        remaining = effective_sources(self.collection, edits)
        self.assertEqual(lineage, 'OSM-1')
        self.assertEqual(len(remaining), 2)
        self.assertEqual({tuple(map(tuple, f['geometry']['coordinates'])) for f in remaining},
                         {tuple(map(tuple, self.points[:2])), tuple(map(tuple, self.points[2:]))})
        self.assertEqual({f['properties']['source_lineage_id'] for f in remaining}, {'OSM-1'})
        self.assertEqual(self.collection, self.original)

    def test_preferred_cuts_do_not_touch_other_lineages(self):
        cuts = preferred_cuts(self.collection['features'], self.children, {'OSM-1'})
        self.assertEqual(len(cuts['OSM-1']), 2)
        self.assertEqual(preferred_cuts(self.collection['features'], self.children, {'OTHER'}), {})


if __name__ == '__main__':
    unittest.main()
