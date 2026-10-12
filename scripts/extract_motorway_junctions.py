#!/usr/bin/env python3
"""从 OSM PBF 中提取 highway=motorway_junction 点要素为 GeoJSON。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from inspect_pbf_highways import _fields, _packed_uints, _read_blocks, _varint


def _signed(value: int) -> int:
    """把 protobuf sint64/sint32 的 zigzag 编码还原为有符号整数。"""
    return (value >> 1) ^ -(value & 1)


def _packed_signed(data: memoryview) -> list[int]:
    values: list[int] = []
    offset = 0
    while offset < len(data):
        value, offset = _varint(data, offset)
        values.append(_signed(value))
    return values


def _tag_map(fields: list[tuple[int, int, int | memoryview]], strings: list[str]) -> dict[str, str]:
    keys: list[int] = []
    values: list[int] = []
    for field, wire_type, value in fields:
        if field in (2, 3):
            numbers = _packed_uints(value) if wire_type == 2 else [int(value)]
            (keys if field == 2 else values).extend(numbers)
    if len(keys) != len(values):
        return {}
    try:
        return {strings[key]: strings[value] for key, value in zip(keys, values)}
    except IndexError:
        return {}


def extract_motorway_junctions(pbf_path: Path) -> dict:
    """读取普通 Node 和 DenseNodes，保留出入口原始标签及 PBF 坐标。"""
    granularity = 100
    lat_offset = 0
    lon_offset = 0
    features: list[dict] = []

    for block_type, block in _read_blocks(pbf_path):
        if block_type == "OSMHeader":
            for field, _wire, value in _fields(block):
                if field == 17:
                    granularity = int(value)
                elif field == 19:
                    lat_offset = _signed(int(value))
                elif field == 20:
                    lon_offset = _signed(int(value))
            continue
        if block_type != "OSMData":
            continue

        strings: list[str] = []
        groups: list[memoryview] = []
        for field, _wire, value in _fields(block):
            if field == 1:
                strings = [
                    bytes(item).decode("utf-8", errors="replace")
                    for number, _, item in _fields(value) if number == 1
                ]
            elif field == 2:
                groups.append(value)

        for group in groups:
            for field, _wire, payload in _fields(group):
                if field == 1:  # Node
                    node_fields = list(_fields(payload))
                    tags = _tag_map(node_fields, strings)
                    if tags.get("highway") != "motorway_junction":
                        continue
                    node_id = None
                    raw_lat = raw_lon = None
                    for number, _, value in node_fields:
                        if number == 1:
                            node_id = _signed(int(value))
                        elif number == 8:
                            raw_lat = _signed(int(value))
                        elif number == 9:
                            raw_lon = _signed(int(value))
                    if raw_lat is None or raw_lon is None:
                        continue
                    features.append(_feature(node_id, raw_lon, raw_lat, granularity, lon_offset, lat_offset, tags))
                elif field == 2:  # DenseNodes
                    ids: list[int] = []
                    lats: list[int] = []
                    lons: list[int] = []
                    key_values: list[int] = []
                    for number, _wire_type, value in _fields(payload):
                        if number == 1:
                            ids = _packed_signed(value)
                        elif number == 8:
                            lats = _packed_signed(value)
                        elif number == 9:
                            lons = _packed_signed(value)
                        elif number == 10:
                            # keys_vals 是普通 int32，不是 zigzag；每个 Node 的标签以 0 结束。
                            key_values = _packed_uints(value)
                    if not (len(ids) == len(lats) == len(lons)):
                        continue
                    node_id = raw_lat = raw_lon = 0
                    cursor = 0
                    for id_delta, lat_delta, lon_delta in zip(ids, lats, lons):
                        node_id += id_delta
                        raw_lat += lat_delta
                        raw_lon += lon_delta
                        tags: dict[str, str] = {}
                        while cursor < len(key_values) and key_values[cursor] != 0:
                            if cursor + 1 >= len(key_values):
                                cursor = len(key_values)
                                break
                            key, value = key_values[cursor], key_values[cursor + 1]
                            cursor += 2
                            if key < len(strings) and value < len(strings):
                                tags[strings[key]] = strings[value]
                        if cursor < len(key_values):
                            cursor += 1
                        if tags.get("highway") == "motorway_junction":
                            features.append(_feature(node_id, raw_lon, raw_lat, granularity, lon_offset, lat_offset, tags))

    return {"type": "FeatureCollection", "features": features}


def _feature(node_id: int | None, raw_lon: int, raw_lat: int, granularity: int,
             lon_offset: int, lat_offset: int, tags: dict[str, str]) -> dict:
    longitude = 1e-9 * (lon_offset + granularity * raw_lon)
    latitude = 1e-9 * (lat_offset + granularity * raw_lat)
    return {
        "type": "Feature",
        "id": node_id,
        "properties": {"osm_node_id": node_id, **tags},
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="原始 .osm.pbf 文件")
    parser.add_argument("--output", type=Path, required=True, help="输出 Point GeoJSON 文件")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"找不到 PBF 文件：{args.input}")
    collection = extract_motorway_junctions(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"已提取 {len(collection['features'])} 个高速出入口：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
