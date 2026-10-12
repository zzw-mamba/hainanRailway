from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_link_pipeline


ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def test_hainan_pbf_uses_hainan_file_and_id_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"AMAP_KEY": "pipeline-test-key"}):
                with patch.object(run_link_pipeline, "_run_stage", return_value=1) as stage:
                    code = run_link_pipeline.main([
                        "--input", str(ROOT / "data/pbf/hainan-260922.osm.pbf"),
                        "--output-dir", directory,
                    ])
            self.assertEqual(code, 1)
            command = stage.call_args.args[1]
            self.assertEqual(command[command.index("--output-prefix") + 1], "hainan")
            self.assertEqual(command[command.index("--link-id-prefix") + 1], "OSM_HN")

    def test_geojson_to_split_links_and_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, AMAP_KEY="pipeline-test-key")
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts/run_link_pipeline.py"),
                    "--input", str(ROOT / "tests/fixtures/sample_roads.geojson"),
                    "--output-dir", directory,
                    "--max-link-length", "1000",
                ],
                cwd=ROOT, env=environment, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            output = Path(directory)
            collection = json.loads((output / "split/links.geojson").read_text(encoding="utf-8"))
            report = json.loads((output / "split/validation_report.json").read_text(encoding="utf-8"))
            html_page = (output / "links_amap.html").read_text(encoding="utf-8")
            self.assertTrue(report["valid"])
            self.assertGreater(len(collection["features"]), 2)
            self.assertIn("source_link_id", html_page)
            self.assertIn("MAIN__S", html_page)
            self.assertIn("line.on('mouseover'", html_page)
            self.assertIn("AMap.MassMarks", html_page)
            self.assertIn("toggle-endpoints", html_page)

    def test_map_renders_optional_motorway_junction_layer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            junctions = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"osm_node_id": 123, "highway": "motorway_junction", "name": "测试出入口", "ref": "1"},
                    "geometry": {"type": "Point", "coordinates": [110.0, 20.0]},
                }],
            }
            junction_file = root / "junctions.geojson"
            junction_file.write_text(json.dumps(junctions, ensure_ascii=False), encoding="utf-8")
            output_file = root / "map.html"
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts/visualize_guangdong_amap.py"),
                    "--input-file", str(ROOT / "tests/fixtures/sample_roads.geojson"),
                    "--junction-file", str(junction_file),
                    "--output-file", str(output_file),
                ],
                cwd=ROOT,
                env=dict(os.environ, AMAP_KEY="pipeline-test-key"),
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            html_page = output_file.read_text(encoding="utf-8")
            self.assertIn("motorway_junction", html_page)
            self.assertIn("测试出入口", html_page)
            self.assertIn("toggle-junctions", html_page)
            self.assertNotIn('id="toggle-junctions" type="checkbox" checked', html_page)
            self.assertIn("高速出入口", html_page)
            self.assertIn("AMap.CircleMarker", html_page)
            self.assertIn("join(' · ') || '高速匝道'", html_page)
            self.assertIn("map.setLimitBounds(new AMap.Bounds(", html_page)
            self.assertNotIn("113.2644", html_page)
            self.assertNotIn("目的路线编号：", html_page)
            self.assertNotIn("目的地：", html_page)


if __name__ == "__main__":
    unittest.main()
