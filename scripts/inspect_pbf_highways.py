#!/usr/bin/env python3
"""直接统计 OSM PBF 中 motorway / motorway_link Way 的原始标签。

仅解析属性所需的 PBF 字段，不依赖 pyrosm，也不把处理脚本新增的长度、
起终点或 link_id 误认为 PBF 原始属性。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import struct
import zlib
from typing import Iterator


INFO_FIELDS = {1: "version", 2: "timestamp", 3: "changeset", 4: "uid", 5: "user_sid", 6: "visible"}
HIGHWAY_TYPES = ("motorway", "motorway_link")


def _varint(data: memoryview, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift >= 70:
            break
    raise ValueError("PBF 包含无效 varint")


def _fields(data: bytes | memoryview) -> Iterator[tuple[int, int, int | memoryview]]:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        key, offset = _varint(view, offset)
        field, wire_type = key >> 3, key & 7
        if wire_type == 0:
            value, offset = _varint(view, offset)
        elif wire_type == 2:
            size, offset = _varint(view, offset)
            if offset + size > len(view):
                raise ValueError("PBF 字段长度超出数据块")
            value = view[offset:offset + size]
            offset += size
        elif wire_type in (1, 5):
            size = 8 if wire_type == 1 else 4
            if offset + size > len(view):
                raise ValueError("PBF 固定长度字段超出数据块")
            value = view[offset:offset + size]
            offset += size
        else:
            raise ValueError(f"不支持的 PBF wire type: {wire_type}")
        yield field, wire_type, value


def _packed_uints(data: memoryview) -> list[int]:
    values = []
    offset = 0
    while offset < len(data):
        value, offset = _varint(data, offset)
        values.append(value)
    return values


def _read_blocks(path: Path) -> Iterator[tuple[str, bytes]]:
    with path.open("rb") as stream:
        while size_bytes := stream.read(4):
            if len(size_bytes) != 4:
                raise ValueError("PBF 文件末尾的 BlobHeader 长度不完整")
            header_size = struct.unpack(">I", size_bytes)[0]
            if header_size > 64 * 1024:
                raise ValueError("PBF BlobHeader 超过格式允许的大小")
            header = stream.read(header_size)
            if len(header) != header_size:
                raise ValueError("PBF BlobHeader 不完整")
            block_type = None
            data_size = None
            for field, _wire, value in _fields(header):
                if field == 1:
                    block_type = bytes(value).decode("utf-8")
                elif field == 3:
                    data_size = int(value)
            if block_type is None or data_size is None:
                raise ValueError("PBF BlobHeader 缺少 type 或 datasize")
            blob = stream.read(data_size)
            if len(blob) != data_size:
                raise ValueError("PBF Blob 数据不完整")
            raw_size = None
            decoded = None
            for field, _wire, value in _fields(blob):
                if field == 1:
                    decoded = bytes(value)
                elif field == 2:
                    raw_size = int(value)
                elif field == 3:
                    decoded = zlib.decompress(value)
                elif field in (4, 5, 6, 7):
                    raise ValueError("PBF 使用了当前脚本不支持的压缩方式")
            if decoded is None or (raw_size is not None and len(decoded) != raw_size):
                raise ValueError("PBF Blob 解压失败或长度不一致")
            yield block_type, decoded


def _way_details(data: memoryview, strings: list[str]) -> tuple[dict[str, str], list[str]]:
    keys: list[int] = []
    values: list[int] = []
    metadata: list[str] = []
    for field, wire_type, value in _fields(data):
        if field in (2, 3):
            numbers = _packed_uints(value) if wire_type == 2 else [int(value)]
            (keys if field == 2 else values).extend(numbers)
        elif field == 4:
            metadata = [INFO_FIELDS[number] for number, _, _ in _fields(value) if number in INFO_FIELDS]
    if len(keys) != len(values):
        raise ValueError("PBF Way 的标签键值数量不一致")
    try:
        return {strings[key]: strings[value] for key, value in zip(keys, values)}, metadata
    except IndexError as exc:
        raise ValueError("PBF Way 引用了不存在的字符串索引") from exc


def inspect_highway_tags(path: Path) -> dict:
    counts = Counter()
    key_counts: dict[str, Counter] = defaultdict(Counter)
    value_counts: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    metadata_counts: dict[str, Counter] = defaultdict(Counter)
    for block_type, block in _read_blocks(path):
        if block_type != "OSMData":
            continue
        strings: list[str] = []
        groups: list[memoryview] = []
        for field, _wire, value in _fields(block):
            if field == 1:
                strings = [bytes(item).decode("utf-8", errors="replace") for number, _, item in _fields(value) if number == 1]
            elif field == 2:
                groups.append(value)
        for group in groups:
            for field, _wire, way in _fields(group):
                if field != 3:
                    continue
                tags, metadata = _way_details(way, strings)
                road_type = tags.get("highway")
                if road_type not in HIGHWAY_TYPES:
                    continue
                counts[road_type] += 1
                metadata_counts[road_type].update(metadata)
                for key, value in tags.items():
                    key_counts[road_type][key] += 1
                    value_counts[road_type][key][value] += 1
    return {
        "source_pbf": str(path),
        "way_count": dict(counts),
        "structural_fields": ["Way.id", "Way.refs (节点引用)", "Way.info (可选元数据)"],
        "tags": {
            road_type: [
                {"key": key, "ways": count, "top_values": counter.most_common(5)}
                for key, count in sorted(key_counts[road_type].items())
                for counter in [value_counts[road_type][key]]
            ] for road_type in HIGHWAY_TYPES
        },
        "info_fields": {road_type: dict(metadata_counts[road_type]) for road_type in HIGHWAY_TYPES},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="原始 .osm.pbf 文件")
    parser.add_argument("--output", type=Path, help="可选 JSON 报告路径")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"找不到 PBF 文件：{args.input}")
    try:
        report = inspect_highway_tags(args.input.resolve())
    except (OSError, ValueError, zlib.error) as exc:
        parser.exit(1, f"PBF 属性统计失败：{exc}\n")
    for road_type in HIGHWAY_TYPES:
        keys = report["tags"][road_type]
        print(f"{road_type}: {report['way_count'].get(road_type, 0)} 条 Way，{len(keys)} 种标签")
        print("  " + ", ".join(item["key"] for item in keys))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"详细报告：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
