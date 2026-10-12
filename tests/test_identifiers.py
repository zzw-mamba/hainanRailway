"""Project ID stability and reference integrity across data regenerations."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hainan-web/scripts'))
from identifiers import assign_ids, route_token


def feature(old, source, y, ref='G9811', highway='motorway'):
    return {'type': 'Feature', 'properties': {'link_id': old, 'source_link_id': source,
            'id': 123, 'segment_index': 1, 'highway': highway, 'ref': ref},
            'geometry': {'type': 'LineString', 'coordinates': [[110, y], [110, y + 0.001]]}}


class IdentifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'registry.json'
        self.roads = [feature('old-a', 'source-a', 19.8), feature('old-b', 'source-a', 19.801),
                      feature('old-ramp', 'source-ramp', 19.802, None, 'motorway_link')]
        self.relations = [{'currentLinkId': 'old-a', 'nextLinkId': 'old-b', 'source_link_id': 'source-a'}]

    def test_unique_ids_source_groups_and_relations_are_migrated(self):
        before = copy.deepcopy(self.roads)
        mapping = assign_ids(self.roads, self.relations, self.path)
        self.assertEqual(len({m['linkId'] for m in mapping}), 3)
        self.assertEqual(self.roads[0]['properties']['link_id'], 'HN-G9811-M-000001')
        self.assertEqual(self.roads[2]['properties']['link_id'], 'HN-UN-R-000001')
        self.assertEqual(self.roads[0]['properties']['source_link_id'], self.roads[1]['properties']['source_link_id'])
        self.assertEqual(self.relations[0]['currentLinkId'], self.roads[0]['properties']['link_id'])
        self.assertEqual(self.relations[0]['nextLinkId'], self.roads[1]['properties']['link_id'])
        self.assertEqual(self.relations[0]['source_link_id'], self.roads[0]['properties']['source_link_id'])
        for a, b in zip(before, self.roads):
            self.assertEqual(a['geometry'], b['geometry'])
            self.assertEqual(a['properties']['link_id'], b['properties']['osm_link_id'])
            self.assertEqual(a['properties']['source_link_id'], b['properties']['osm_source_link_id'])

    def test_reordering_idempotence_and_new_earlier_geometry_do_not_renumber(self):
        raw = copy.deepcopy(self.roads)
        assign_ids(self.roads, self.relations, self.path)
        before = json.loads(self.path.read_text())['links']
        repeated = assign_ids(self.roads, self.relations, self.path)
        self.assertEqual({m['osmLinkId']: m['linkId'] for m in repeated}, before)
        reordered = list(reversed(raw)) + [feature('new-earlier', 'new-source', 19.0)]
        assign_ids(reordered, [], self.path)
        after = json.loads(self.path.read_text())['links']
        self.assertTrue(all(after[k] == v for k, v in before.items()))
        self.assertEqual(after['new-earlier'], 'HN-G9811-M-000003')

    def test_missing_relationship_and_duplicate_id_fail(self):
        bad = [{'currentLinkId': 'missing', 'nextLinkId': 'old-b'}]
        with self.assertRaises(ValueError):
            assign_ids(self.roads, bad, self.path)
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            assign_ids(self.roads + [copy.deepcopy(self.roads[0])], [], self.path)

    def test_removed_id_is_reserved_and_direction_is_not_part_of_id(self):
        assign_ids(self.roads, [], self.path)
        old_id = self.roads[0]['properties']['link_id']
        subset = [feature('brand-new', 'new-source', 18.5)]
        assign_ids(subset, [], self.path)
        self.assertNotEqual(subset[0]['properties']['link_id'], old_id)
        self.roads[0]['properties']['direction_annotation'] = {'code': 'DOWN'}
        assign_ids(self.roads, [], self.path)
        self.assertEqual(self.roads[0]['properties']['link_id'], old_id)

    def test_shared_route_normalization_is_deterministic(self):
        self.assertEqual(route_token('G75;G15'), 'G15+G75')
        self.assertEqual(route_token('G15;G75;G15'), 'G15+G75')
        self.assertEqual(route_token(None), 'UN')

    def test_changed_split_boundary_gets_new_id_and_restoring_boundary_reuses_id(self):
        original = copy.deepcopy(self.roads)
        assign_ids(self.roads, self.relations, self.path)
        old_id = self.roads[0]['properties']['link_id']
        changed = copy.deepcopy(original)
        changed[0]['geometry']['coordinates'][-1][1] += 0.001
        relationships = [{'currentLinkId': 'old-a', 'nextLinkId': 'old-b'}]
        assign_ids(changed, relationships, self.path)
        new_id = changed[0]['properties']['link_id']
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(changed[0]['properties']['source_link_id'], self.roads[0]['properties']['source_link_id'])
        self.assertEqual(changed[0]['properties']['osm_link_id'], 'old-a')
        self.assertEqual(relationships[0]['currentLinkId'], new_id)
        assign_ids(changed, relationships, self.path)
        self.assertEqual(changed[0]['properties']['link_id'], new_id)
        assign_ids(original, [], self.path)
        self.assertEqual(original[0]['properties']['link_id'], old_id)

    def test_route_or_road_type_change_updates_project_id_prefix(self):
        raw = copy.deepcopy(self.roads)
        assign_ids(self.roads, [], self.path)
        old = self.roads[0]['properties']['link_id']
        changed = copy.deepcopy(raw)
        changed[0]['properties']['ref'] = 'G98'
        changed[0]['properties']['highway'] = 'motorway_link'
        assign_ids(changed, [], self.path, previous_features=self.roads)
        self.assertTrue(changed[0]['properties']['link_id'].startswith('HN-G98-R-'))
        self.assertNotEqual(changed[0]['properties']['link_id'], old)
        assign_ids(changed, [], self.path)
        self.assertTrue(changed[0]['properties']['link_id'].startswith('HN-G98-R-'))


if __name__ == '__main__':
    unittest.main()
