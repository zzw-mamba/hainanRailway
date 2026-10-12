#!/usr/bin/env python3
"""将现有 GeoJSON Link 拆成受长度和匝道拓扑约束的细粒度 Link。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

from link_splitting import (
    SplitConfig, SplitError, load_dotenv, rename_link_id, split_links, update_mapping_link_id,
    validate_split_result,
)
from osm_topology import extract_node_index, junction_cuts, build_topology
from merge_highway import merge_highway_sources


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def read_features(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = read_json(path)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise SplitError("输入必须是 GeoJSON FeatureCollection")
    return data, data["features"]


def read_relationships(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = read_json(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("features"), list):
        return [feature.get("properties", {}) for feature in data["features"]]
    # 支持 fetch_gis_data.py 保留下来的 JSON-RPC 原始响应。
    try:
        records = data["result"]["result"]
    except (KeyError, TypeError) as exc:
        raise SplitError("关系文件应为 JSON 数组、FeatureCollection 或 JSON-RPC 原始响应") from exc
    if not isinstance(records, list):
        raise SplitError("关系文件 result.result 必须是数组")
    return records


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def write_mapping_csv(path: Path, mapping: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_link_id", "input_link_id", "segment_link_ids", "forced_split_points_m", "skipped"], lineterminator="\n")
        writer.writeheader()
        for row in mapping:
            writer.writerow({
                **row,
                "segment_link_ids": ";".join(row.get("segment_link_ids", [])),
                "forced_split_points_m": ";".join(map(str, row.get("forced_split_points_m", []))),
            })


def parse_args() -> argparse.Namespace:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="输入路网 GeoJSON FeatureCollection")
    parser.add_argument("--output-dir", type=Path, required=True, help="输出目录（不会覆盖输入）")
    parser.add_argument("--relationships", type=Path, help="可选的原始路链连通关系 JSON")
    parser.add_argument("--osm-pbf", type=Path, help="从同源 PBF 共享节点补齐跨原链有向拓扑")
    parser.add_argument("--link-id-field", default="auto", help="路链 ID 字段；默认优先 link_id，其次 id")
    parser.add_argument("--max-link-length", type=float, help="覆盖 .env 中的 MAX_LINK_LENGTH（米）")
    parser.add_argument("--snap-tolerance-m", type=float, help="端点匹配容差（米）")
    parser.add_argument("--min-segment-length-m", type=float, help="近零子段合并阈值（米）")
    parser.add_argument("--metric-mode", choices=("auto", "web-mercator", "planar"), help="长度计算模式")
    parser.add_argument("--resplit-existing", action="store_true", help="允许再次处理已有 source_link_id/segment_index 的数据")
    parser.add_argument("--rename-link-id", nargs=2, metavar=("OLD", "NEW"), help="拆分完成后安全改名一个 Link ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        collection, features = read_features(args.input)
        relationships = read_relationships(args.relationships)
        config = SplitConfig.from_environment()
        overrides = {
            "max_link_length": args.max_link_length,
            "snap_tolerance_m": args.snap_tolerance_m,
            "min_segment_length_m": args.min_segment_length_m,
            "metric_mode": args.metric_mode,
        }
        config = SplitConfig(**{**config.__dict__, **{key: value for key, value in overrides.items() if value is not None}, "skip_already_split": not args.resplit_existing})
        node_index = extract_node_index(args.osm_pbf, features) if args.osm_pbf else None
        if node_index:
            features = merge_highway_sources(features, node_index)
        result = split_links(features, relationships, config, args.link_id_field,
                             junction_cuts(features, node_index, config.metric_mode) if node_index else None)
        if args.rename_link_id:
            result.features, result.relationships = rename_link_id(
                result.features, result.relationships, *args.rename_link_id, args.link_id_field,
            )
            result.mapping = update_mapping_link_id(result.mapping, *args.rename_link_id)
        topology_report = None
        if node_index:
            result.relationships, topology_report = build_topology(result.features, node_index)
        report = validate_split_result(features, result, config, args.link_id_field)
        output_collection = {key: value for key, value in collection.items() if key != "features"}
        output_collection["features"] = result.features
        output_collection["linkSplit"] = {
            "maxLinkLengthM": config.max_link_length,
            "snapToleranceM": config.snap_tolerance_m,
            "minSegmentLengthM": config.min_segment_length_m,
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.output_dir / "links.geojson", output_collection)
        write_json(args.output_dir / "link_relationships.json", result.relationships)
        write_json(args.output_dir / "link_mapping.json", result.mapping)
        write_mapping_csv(args.output_dir / "link_mapping.csv", result.mapping)
        write_json(args.output_dir / "validation_report.json", report.as_dict())
        if topology_report:
            write_json(args.output_dir / "topology_report.json", topology_report)
        print(f"已输出 {len(result.features)} 条细粒度 Link：{args.output_dir / 'links.geojson'}")
        print(f"映射关系：{args.output_dir / 'link_mapping.json'}")
        print(f"校验结果：{args.output_dir / 'validation_report.json'}")
        if not report.valid:
            print("拆分结果校验失败：" + "；".join(report.errors), file=sys.stderr)
            return 1
        if report.warnings:
            print(f"校验通过，但有 {len(report.warnings)} 条警告。")
        else:
            print("校验通过。")
        return 0
    except (OSError, json.JSONDecodeError, SplitError, ValueError) as exc:
        print(f"拆分失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
