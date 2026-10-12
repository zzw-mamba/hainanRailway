"""Generation input limits and failure isolation with the actual splitter."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hainan-web/scripts'))
import generate_data
from osm_topology import NodeIndex


class GenerationTests(unittest.TestCase):
    def test_length_rejects_nonfinite_and_outside_limits(self):
        for value in [0, 99, 10001, float('nan'), float('inf'), -float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                generate_data.validate_length(value)
        self.assertEqual(generate_data.validate_length(100), 100)
        self.assertEqual(generate_data.validate_length(10000), 10000)

    def test_failure_keeps_snapshot_and_registry_and_removes_staging_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'outputs/hainan/source'
            baseline = root / 'outputs/hainan/split'
            source.mkdir(parents=True)
            baseline.mkdir()
            feature = {'type': 'Feature', 'properties': {'link_id': 'original', 'source_link_id': 'original',
                       'segment_index': 1, 'highway': 'motorway', 'ref': 'G98'},
                       'geometry': {'type': 'LineString', 'coordinates': [[500000, 0], [502000, 0]]}}
            collection = {'type': 'FeatureCollection', 'features': [feature]}
            source_collection = copy.deepcopy(collection)
            del source_collection['features'][0]['properties']['source_link_id']
            del source_collection['features'][0]['properties']['segment_index']
            (source / 'hainan_roads.geojson').write_text(json.dumps(source_collection))
            (baseline / 'links.geojson').write_text(json.dumps(collection))
            (baseline / 'link_relationships.json').write_text('[]')
            public = root / 'public'
            public.mkdir()
            snapshot = public / 'hainan.json'
            snapshot.write_text('{"roads":[],"generation":{"maxLinkLengthM":500}}')
            with patch.object(generate_data, 'ROOT', root), patch.object(generate_data, 'OUT', public), \
                 patch.object(generate_data, 'extract_node_index', return_value=NodeIndex({}, {})), \
                 patch.object(generate_data, 'prepare', side_effect=ValueError('association failed')):
                with self.assertRaisesRegex(ValueError, 'association failed'):
                    generate_data.regenerate(1000)
            self.assertEqual(snapshot.read_text(), '{"roads":[],"generation":{"maxLinkLengthM":500}}')
            self.assertFalse((root / 'outputs/identifiers/link_id_registry.json').exists())
            self.assertFalse((root / 'outputs/hainan/generated').exists())
            self.assertFalse(list((root / 'outputs').glob('.web-generation-*')))


if __name__ == '__main__':
    unittest.main()
