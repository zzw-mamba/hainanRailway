"""Merging must cross simple source boundaries but retain real junctions."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from link_splitting import SplitConfig, split_links
from merge_highway import merge_highway_sources, annotate_merged_children
from osm_topology import NodeIndex, junction_cuts


def road(identifier, way, points, ref='G9811', highway='motorway'):
    return {'type': 'Feature', 'properties': {'link_id': identifier, 'id': way,
            'ref': ref, 'highway': highway, 'oneway': 'yes', 'name': '海三高速'},
            'geometry': {'type': 'LineString', 'coordinates': points}}


class MergeHighwayTests(unittest.TestCase):
    def test_simple_continuation_splits_across_original_boundary(self):
        features = [road('a', 1, [[0, 0], [3, 0]]), road('b', 2, [[3, 0], [14, 0]])]
        index = NodeIndex({1: [10, 11], 2: [11, 12]},
                          {10: (0, 0), 11: (3, 0), 12: (14, 0)})
        merged = merge_highway_sources(features, index)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['properties']['merged_source_ids'], ['a', 'b'])
        self.assertEqual(index.node_at(merged[0], (14, 0)), 12)
        result = split_links(merged, config=SplitConfig(max_link_length=10, metric_mode='planar'),
                             forced_split_points_by_link=junction_cuts(merged, index, 'planar'))
        self.assertEqual(len(result.features), 2)
        self.assertEqual(result.features[0]['geometry']['coordinates'][-1], [7.0, 0.0])

    def test_ramp_junction_prevents_merging(self):
        features = [road('a', 1, [[0, 0], [3, 0]]), road('b', 2, [[3, 0], [14, 0]]),
                    road('r', 3, [[3, 0], [3, 1]], highway='motorway_link')]
        index = NodeIndex({1: [10, 11], 2: [11, 12], 3: [11, 13]},
                          {10: (0, 0), 11: (3, 0), 12: (14, 0), 13: (3, 1)})
        self.assertEqual(len(merge_highway_sources(features, index)), 3)

    def test_attribute_change_stays_traceable_without_forcing_original_cut(self):
        features = [road('a', 1, [[0, 0], [3, 0]]), road('b', 2, [[3, 0], [14, 0]])]
        features[0]['properties']['bridge'] = 'yes'
        index = NodeIndex({1: [10, 11], 2: [11, 12]},
                          {10: (0, 0), 11: (3, 0), 12: (14, 0)})
        merged = merge_highway_sources(features, index)
        self.assertEqual(len(merged), 1)
        result = split_links(merged, config=SplitConfig(max_link_length=10, metric_mode='planar'))
        annotate_merged_children(result.features, merged)
        first, second = result.features
        self.assertEqual(first['geometry']['coordinates'][-1], [7.0, 0.0])
        self.assertNotIn('bridge', first['properties'])
        self.assertEqual(len(first['properties']['source_sections']), 2)
        self.assertEqual(first['properties']['osm_way_ids'], [1, 2])
        self.assertNotIn('bridge', second['properties'])
        self.assertEqual(second['properties']['osm_way_ids'], [2])

    def test_junction_inside_merged_chain_remains_a_cut(self):
        features = [road('a', 1, [[0, 0], [3, 0]]),
                    road('b', 2, [[3, 0], [7, 0], [14, 0]]),
                    road('r', 3, [[7, 0], [7, 1]], highway='motorway_link')]
        index = NodeIndex({1: [10, 11], 2: [11, 12, 13], 3: [12, 14]},
                          {10: (0, 0), 11: (3, 0), 12: (7, 0),
                           13: (14, 0), 14: (7, 1)})
        merged = merge_highway_sources(features, index)
        main = next(feature for feature in merged if feature['properties'].get('merged_source_ids'))
        cuts = junction_cuts(merged, index, 'planar')
        self.assertEqual(cuts[main['properties']['link_id']], [7.0])
        result = split_links(merged, config=SplitConfig(max_link_length=10, metric_mode='planar'),
                             forced_split_points_by_link=cuts)
        main_children = [feature for feature in result.features
                         if feature['properties'].get('source_link_id') == main['properties']['link_id']]
        self.assertEqual(main_children[0]['geometry']['coordinates'][-1], [7.0, 0.0])

    def test_different_route_or_direction_does_not_merge(self):
        features = [road('a', 1, [[0, 0], [3, 0]]), road('b', 2, [[3, 0], [14, 0]], ref='G9813')]
        index = NodeIndex({1: [10, 11], 2: [11, 12]},
                          {10: (0, 0), 11: (3, 0), 12: (14, 0)})
        self.assertEqual(len(merge_highway_sources(features, index)), 2)
        features[1]['properties']['ref'] = 'G9811'
        features[1]['properties']['oneway'] = 'no'
        self.assertEqual(len(merge_highway_sources(features, index)), 2)


if __name__ == '__main__':
    unittest.main()
