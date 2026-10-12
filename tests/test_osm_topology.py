"""Shared-node evidence, directed transitions and preservation of junctions."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from osm_topology import NodeIndex, build_topology, extract_node_index, junction_cuts
from link_splitting import SplitConfig, split_links, validate_split_result


def feature(identifier, way, points, oneway='yes', source=None, segment=1):
    return {'type': 'Feature', 'properties': {'link_id': identifier, 'id': way, 'oneway': oneway,
            'source_link_id': source or identifier, 'segment_index': segment, 'highway': 'motorway'},
            'geometry': {'type': 'LineString', 'coordinates': points}}


def pairs(relations):
    return {(r['currentLinkId'], r['nextLinkId']) for r in relations}


def varint(value):
    if value < 0:
        value += 2**64
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    return bytes(output + bytes([value]))


def signed(value):
    return varint((value << 1) ^ (value >> 63))


def field(number, value, packed=False):
    return varint((number << 3) | (2 if packed else 0)) + (varint(len(value)) + value if packed else varint(value))


class TopologyTests(unittest.TestCase):
    def test_cross_source_and_internal_connections_follow_direction(self):
        features = [feature('A1', 1, [[0, 0], [10, 0]], source='A', segment=1),
                    feature('A2', 1, [[10, 0], [20, 0]], source='A', segment=2),
                    feature('B', 2, [[20, 0], [30, 0]]),
                    feature('wrong-way', 3, [[30, 0], [20, 0]])]
        index = NodeIndex({1: [1, 2], 2: [2, 3], 3: [3, 2]}, {1: [0, 0], 2: [20, 0], 3: [30, 0]})
        relations, report = build_topology(features, index)
        self.assertIn(('A1', 'A2'), pairs(relations))
        self.assertIn(('A2', 'B'), pairs(relations))
        self.assertNotIn(('A2', 'wrong-way'), pairs(relations))
        self.assertNotIn(('B', 'A2'), pairs(relations))
        self.assertEqual(next(r for r in relations if r['currentLinkId'] == 'A2')['osmNodeId'], 2)
        self.assertTrue(report['valid'])

    def test_same_coordinates_with_different_osm_nodes_do_not_connect(self):
        features = [feature('bridge', 1, [[0, 0], [10, 0]]),
                    feature('underpass', 2, [[10, 0], [20, 0]]),
                    feature('crossing', 3, [[5, -5], [5, 5]])]
        index = NodeIndex({1: [1, 2], 2: [3, 4], 3: [5, 6]},
                          {1: [0, 0], 2: [10, 0], 3: [10, 0], 4: [20, 0], 5: [5, -5], 6: [5, 5]})
        relations, _ = build_topology(features, index)
        self.assertFalse(relations)

    def test_reverse_oneway_and_bidirectional_segments_are_supported(self):
        features = [feature('A', 1, [[0, 0], [10, 0]], 'no', source='same', segment=1),
                    feature('B', 1, [[10, 0], [20, 0]], 'no', source='same', segment=2),
                    feature('reverse', 2, [[30, 0], [20, 0]], '-1')]
        index = NodeIndex({1: [1, 2], 2: [3, 2]}, {1: [0, 0], 2: [20, 0], 3: [30, 0]})
        relations, _ = build_topology(features, index)
        self.assertTrue({('A', 'B'), ('B', 'A'), ('B', 'reverse')} <= pairs(relations))
        self.assertFalse(any(a == b for a, b in pairs(relations)))
        reverse = next(r for r in relations if r['nextLinkId'] == 'reverse')
        self.assertEqual(reverse['nextOrientation'], 'reverse')

    def test_unknown_direction_and_unresolved_coordinates_are_not_guessed(self):
        features = [feature('known', 1, [[0, 0], [10, 0]]),
                    feature('unknown', 2, [[10, 0], [20, 0]], None),
                    feature('no-node-evidence', 999, [[10, 0], [30, 0]])]
        index = NodeIndex({1: [1, 2], 2: [2, 3]}, {1: [0, 0], 2: [10, 0], 3: [20, 0]})
        relations, report = build_topology(features, index)
        self.assertFalse(relations)
        self.assertEqual(report['unknownDirectionLinks'], ['unknown'])
        self.assertEqual(len(report['unresolvedSourceEndpoints']), 2)

    def test_internal_shared_junction_is_cut_even_near_an_endpoint(self):
        features = [feature('main', 1, [[0, 0], [.2, 0], [50, 0]]),
                    feature('exit', 2, [[.2, 0], [.2, 10]])]
        for f in features:
            del f['properties']['source_link_id']
            del f['properties']['segment_index']
        index = NodeIndex({1: [1, 2, 3], 2: [2, 4]}, {1: [0, 0], 2: [.2, 0], 3: [50, 0], 4: [.2, 10]})
        cuts = junction_cuts(features, index, 'planar')
        self.assertEqual(cuts['main'], [.2])
        _, before = build_topology(copy.deepcopy(features), index)
        self.assertFalse(before['valid'])
        config = SplitConfig(max_link_length=100, metric_mode='planar')
        result = split_links(features, config=config, forced_split_points_by_link=cuts)
        relations, after = build_topology(result.features, index)
        self.assertTrue(after['valid'])
        self.assertTrue(validate_split_result(features, result, config).valid)
        self.assertIn(('main__S001', 'exit'), pairs(relations))
        self.assertEqual(features[0]['geometry']['coordinates'], [[0, 0], [.2, 0], [50, 0]])

    def test_pbf_reader_decodes_refs_and_block_coordinate_metadata(self):
        # Dense IDs 1,2; Way 10 refs 1,2. Non-default PrimitiveBlock metadata.
        dense = field(1, signed(1) + signed(1), True) + field(8, signed(100) + signed(5), True) + field(9, signed(200) + signed(7), True)
        way = field(1, 10) + field(8, signed(1) + signed(1), True)
        ordinary = field(1, 3 << 1) + field(8, 110 << 1) + field(9, 220 << 1)
        group = field(2, dense, True) + field(3, way, True) + field(1, ordinary, True)
        block = field(2, group, True) + field(17, 1000) + field(19, 1000000000) + field(20, -1000000000)
        blob = field(1, block, True)
        header = field(1, b'OSMData', True) + field(3, len(blob))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.pbf'
            path.write_bytes(struct.pack('>I', len(header)) + header + blob)
            index = extract_node_index(path, [feature('A', 10, [[0, 0], [1, 0]])])
        self.assertEqual(index.way_nodes[10], [1, 2])
        self.assertEqual(set(index.coordinates), {1, 2})
        self.assertAlmostEqual(index.coordinates[1][0], -.9998)
        self.assertAlmostEqual(index.coordinates[2][1], 1.000105)

    def test_real_hainan_cross_source_evidence_and_geometry_preservation(self):
        features = json.loads((ROOT / 'outputs/hainan/split/links.geojson').read_text())['features']
        before = copy.deepcopy(features)
        index = extract_node_index(ROOT / 'data/pbf/hainan-260922.osm.pbf', features)
        relationships, report = build_topology(features, index)
        lookup = {f['properties']['link_id']: f for f in features}
        self.assertEqual(len(report['unresolvedSourceEndpoints']), 0)
        self.assertGreater(report['crossSourceRelationships'], 4000)
        signatures = {(r['currentLinkId'], r['nextLinkId'], r['junctionNode'], r['currentOrientation'], r['nextOrientation']) for r in relationships}
        self.assertEqual(len(signatures), len(relationships))
        for r in relationships:
            current, following = lookup[r['currentLinkId']], lookup[r['nextLinkId']]
            if r['relationship_type'] == 'osm_cross_source':
                a = current['properties']['topology']['endOsmNodeId']
                b = following['properties']['topology']['startOsmNodeId']
                if r['currentOrientation'] == 'reverse':
                    a = current['properties']['topology']['startOsmNodeId']
                if r['nextOrientation'] == 'reverse':
                    b = following['properties']['topology']['endOsmNodeId']
                self.assertEqual(a, b)
                self.assertEqual(a, r['osmNodeId'])
        for a, b in zip(before, features):
            self.assertEqual(a['geometry'], b['geometry'])
            self.assertEqual(a['properties'], {k: v for k, v in b['properties'].items() if k != 'topology'})


if __name__ == '__main__':
    unittest.main()
