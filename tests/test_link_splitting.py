from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


import unittest

from link_splitting import (
    MeasuredLine, SplitConfig, SplitError, rename_link_id, split_links, update_mapping_link_id,
    validate_split_result,
)


def feature(link_id: str, coordinates: list[list[float]], **properties: object) -> dict:
    return {
        "type": "Feature",
        "properties": {"link_id": link_id, "highway": "motorway", "name": "测试道路", **properties},
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def config(**changes: object) -> SplitConfig:
    defaults = {
        "max_link_length": 100.0,
        "metric_mode": "planar",
        "snap_tolerance_m": 0.1,
        "min_segment_length_m": 1.0,
    }
    defaults.update(changes)
    return SplitConfig(**defaults)


class LinkSplittingTests(unittest.TestCase):
    def assert_valid(self, inputs: list[dict], result: object, settings: SplitConfig) -> None:
        report = validate_split_result(inputs, result, settings)
        self.assertTrue(report.valid, report.errors)

    def test_short_link_is_not_reidentified(self) -> None:
        inputs = [feature("A", [[0, 0], [80, 0]], lanes="2")]
        result = split_links(inputs, config=config())
        self.assertEqual([item["properties"]["link_id"] for item in result.features], ["A"])
        self.assertEqual(result.features[0]["properties"]["source_link_id"], "A")
        self.assertEqual(result.features[0]["properties"]["lanes"], "2")
        self.assert_valid(inputs, result, config())

    def test_length_split_is_even_and_bounded(self) -> None:
        inputs = [feature("A", [[0, 0], [230, 0]])]
        result = split_links(inputs, config=config(max_link_length=100))
        lengths = [MeasuredLine.from_geometry(item["geometry"], "planar").length for item in result.features]
        self.assertEqual(len(lengths), 3)
        self.assertTrue(all(length <= 100 for length in lengths))
        for length in lengths:
            self.assertAlmostEqual(length, 230 / 3)
        self.assert_valid(inputs, result, config(max_link_length=100))

    def test_exact_boundary_does_not_split(self) -> None:
        inputs = [feature("A", [[0, 0], [100, 0]])]
        result = split_links(inputs, config=config())
        self.assertEqual(len(result.features), 1)
        self.assert_valid(inputs, result, config())

    def test_ramp_endpoint_forces_internal_split(self) -> None:
        main = feature("MAIN", [[0, 0], [50, 0], [100, 0]])
        ramp = feature("RAMP", [[50, 0], [50, 30]], highway="motorway_link")
        result = split_links([main, ramp], config=config(max_link_length=200))
        children = [item for item in result.features if item["properties"]["source_link_id"] == "MAIN"]
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0]["geometry"]["coordinates"][-1], [50.0, 0.0])
        self.assert_valid([main, ramp], result, config(max_link_length=200))

    def test_ramp_endpoint_on_line_segment_without_existing_vertex_forces_split(self) -> None:
        main = feature("MAIN", [[0, 0], [100, 0]])
        ramp = feature("RAMP", [[50, 0], [50, 30]], highway="motorway_link")
        result = split_links([main, ramp], config=config(max_link_length=200))
        children = [item for item in result.features if item["properties"]["source_link_id"] == "MAIN"]
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0]["geometry"]["coordinates"][-1], [50.0, 0.0])

    def test_multiple_ramps_and_length_split(self) -> None:
        main = feature("MAIN", [[0, 0], [20, 0], [220, 0], [240, 0]])
        ramps = [
            feature("R1", [[20, 0], [20, 20]], highway="motorway_link"),
            feature("R2", [[220, 0], [220, 20]], highway="motorway_link"),
        ]
        settings = config(max_link_length=80)
        result = split_links([main, *ramps], config=settings)
        main_children = [item for item in result.features if item["properties"]["source_link_id"] == "MAIN"]
        self.assertEqual(len(main_children), 5)  # 20 + 3*(约 66.7) + 20
        self.assert_valid([main, *ramps], result, settings)

    def test_near_endpoint_forced_point_is_merged(self) -> None:
        main = feature("MAIN", [[0, 0], [0.5, 0], [100, 0]])
        ramp = feature("RAMP", [[0.5, 0], [0.5, 10]], highway="motorway_link")
        result = split_links([main, ramp], config=config(max_link_length=200))
        children = [item for item in result.features if item["properties"]["source_link_id"] == "MAIN"]
        self.assertEqual(len(children), 1)
        self.assertTrue(any("端点" in warning for warning in result.warnings))

    def test_polyline_cut_keeps_length_and_continuity(self) -> None:
        inputs = [feature("A", [[0, 0], [60, 0], [60, 80], [160, 80]])]
        settings = config(max_link_length=100)
        result = split_links(inputs, config=settings)
        self.assertEqual(len(result.features), 3)
        self.assert_valid(inputs, result, settings)

    def test_relationships_are_rebuilt(self) -> None:
        inputs = [feature("A", [[0, 0], [200, 0]]), feature("B", [[200, 0], [250, 0]])]
        relations = [{"id": "r1", "currentLinkId": "A", "nextLinkId": "B", "direction": "UP"}]
        settings = config(max_link_length=100)
        result = split_links(inputs, relations, settings)
        a_ids = result.mapping[0]["segment_link_ids"]
        self.assertEqual(result.relationships[0]["currentLinkId"], a_ids[-1])
        self.assertEqual(result.relationships[0]["nextLinkId"], "B")
        self.assertEqual(sum(row.get("relationship_type") == "split_internal" for row in result.relationships), 1)
        self.assert_valid(inputs, result, settings)

    def test_link_id_generation_avoids_collision(self) -> None:
        inputs = [feature("A", [[0, 0], [200, 0]]), feature("A__S001", [[300, 0], [350, 0]])]
        result = split_links(inputs, config=config())
        ids = [row["properties"]["link_id"] for row in result.features]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("A__S001_2", ids)

    def test_duplicate_input_id_is_rejected(self) -> None:
        with self.assertRaises(SplitError):
            split_links([feature("A", [[0, 0], [10, 0]]), feature("A", [[20, 0], [30, 0]])], config=config())

    def test_rename_updates_relationship_and_rejects_duplicate(self) -> None:
        inputs = [feature("A", [[0, 0], [10, 0]]), feature("B", [[10, 0], [20, 0]])]
        features, relationships = rename_link_id(inputs, [{"currentLinkId": "A", "nextLinkId": "B"}], "A", "C")
        self.assertEqual(features[0]["properties"]["link_id"], "C")
        self.assertEqual(relationships[0]["currentLinkId"], "C")
        with self.assertRaises(SplitError):
            rename_link_id(features, relationships, "C", "B")

    def test_rename_updates_mapping_but_not_source_lineage(self) -> None:
        mapping = [{"source_link_id": "A", "input_link_id": "A", "segment_link_ids": ["A__S001", "A__S002"]}]
        renamed = update_mapping_link_id(mapping, "A__S001", "CUSTOM")
        self.assertEqual(renamed[0]["source_link_id"], "A")
        self.assertEqual(renamed[0]["segment_link_ids"], ["CUSTOM", "A__S002"])

    def test_invalid_geometry_is_rejected(self) -> None:
        bad = feature("A", [[0, 0], [0, 0]])
        with self.assertRaises(SplitError):
            split_links([bad], config=config())

    def test_second_run_is_idempotent_by_default(self) -> None:
        inputs = [feature("A", [[0, 0], [200, 0]])]
        settings = config()
        first = split_links(inputs, config=settings)
        second = split_links(first.features, first.relationships, settings)
        self.assertEqual(
            [row["properties"]["link_id"] for row in first.features],
            [row["properties"]["link_id"] for row in second.features],
        )
        self.assert_valid(first.features, second, settings)


if __name__ == "__main__":
    unittest.main()
