#!/usr/bin/env python3
"""一条命令完成 OSM 路网读取、路链拆分、校验和高德地图 HTML 生成。

输入可以是 .osm.pbf，也可以是项目已有的 WGS84 GeoJSON。各阶段复用项目
现有脚本，输出保存在同一目录下，方便追溯原始数据和拆分结果。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from link_splitting import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=Path(os.getenv("PBF_FILE", str(BASE_DIR / "data/pbf/guangdong-260921.osm.pbf"))),
        help="输入 .osm.pbf 或现有 WGS84 .geojson；默认读取 PBF_FILE",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=BASE_DIR / "outputs/link_pipeline",
        help="全流程输出目录；默认项目内 outputs/link_pipeline",
    )
    parser.add_argument("--max-link-length", type=float, help="单条 Link 最大长度（米）；默认读取 MAX_LINK_LENGTH")
    parser.add_argument("--relationships", type=Path, help="可选：原始 Link 连通关系 JSON")
    parser.add_argument("--junction-file", type=Path, help="可选：高速出入口 Point GeoJSON；PBF 输入默认自动提取")
    parser.add_argument("--highway", nargs="+", help="PBF 提取时保留的 highway 类型")
    parser.add_argument("--all-drivable", action="store_true", help="PBF 提取时保留全部可驾驶道路")
    parser.add_argument("--snap-tolerance-m", type=float, help="拓扑端点匹配容差（米）")
    parser.add_argument("--min-segment-length-m", type=float, help="近零子段阈值（米）")
    return parser.parse_args(argv)


def _run_stage(label: str, arguments: list[str]) -> int:
    print(f"\n[{label}]", flush=True)
    try:
        return subprocess.run([sys.executable, *arguments], cwd=BASE_DIR, check=False).returncode
    except OSError as exc:
        print(f"{label} 无法启动：{exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not source.is_file():
        print(f"找不到输入数据：{source}", file=sys.stderr)
        return 2
    if not os.getenv("AMAP_KEY"):
        print("缺少 AMAP_KEY；请在项目 .env 中配置高德 Web 端 Key。", file=sys.stderr)
        return 2
    if args.highway and args.all_drivable:
        print("--highway 与 --all-drivable 不能同时使用。", file=sys.stderr)
        return 2
    if args.relationships and not args.relationships.expanduser().is_file():
        print(f"找不到关系文件：{args.relationships}", file=sys.stderr)
        return 2

    name = source.name.lower()
    junction_file = args.junction_file.expanduser().resolve() if args.junction_file else None
    if name.endswith(".osm.pbf"):
        raw_dir = output_dir / "source"
        region = re.sub(r"[^a-z0-9_]+", "_", name[:-len(".osm.pbf")].split("-")[0]) or "roads"
        region_code = {"guangdong": "GD", "hainan": "HN"}.get(region, region.upper())
        command = [
            str(SCRIPT_DIR / "process_guangdong_pbf.py"),
            "--pbf", str(source), "--output-dir", str(raw_dir),
            "--output-prefix", region, "--link-id-prefix", f"OSM_{region_code}",
        ]
        if args.highway:
            command.extend(["--highway", *args.highway])
        if args.all_drivable:
            command.append("--all-drivable")
        code = _run_stage("1/3 读取与处理 PBF", command)
        if code:
            return code
        geojson = raw_dir / f"{region}_roads.geojson"
        if junction_file is None:
            junction_file = raw_dir / f"{region}_motorway_junctions.geojson"
            code = _run_stage("1b/3 提取高速出入口", [
                str(SCRIPT_DIR / "extract_motorway_junctions.py"),
                "--input", str(source), "--output", str(junction_file),
            ])
            if code:
                return code
    elif name.endswith(".geojson"):
        if args.highway or args.all_drivable:
            print("--highway 和 --all-drivable 仅适用于 PBF 输入。", file=sys.stderr)
            return 2
        geojson = source
        print(f"[1/3 读取现有 GeoJSON] {geojson}", flush=True)
    else:
        print("输入格式须为 .osm.pbf 或 .geojson。", file=sys.stderr)
        return 2

    split_dir = output_dir / "split"
    command = [
        str(SCRIPT_DIR / "split_links.py"),
        "--input", str(geojson), "--output-dir", str(split_dir),
    ]
    if name.endswith(".osm.pbf"):
        command.extend(["--osm-pbf", str(source)])
    if args.max_link_length is not None:
        command.extend(["--max-link-length", str(args.max_link_length)])
    if args.relationships:
        command.extend(["--relationships", str(args.relationships.expanduser().resolve())])
    if args.snap_tolerance_m is not None:
        command.extend(["--snap-tolerance-m", str(args.snap_tolerance_m)])
    if args.min_segment_length_m is not None:
        command.extend(["--min-segment-length-m", str(args.min_segment_length_m)])
    code = _run_stage("2/3 拆分与校验路链", command)
    if code:
        return code

    html_path = output_dir / "links_amap.html"
    visualization_command = [
        str(SCRIPT_DIR / "visualize_guangdong_amap.py"),
        "--input-file", str(split_dir / "links.geojson"),
        "--output-file", str(html_path),
    ]
    if junction_file:
        if not junction_file.is_file():
            print(f"找不到高速出入口 GeoJSON：{junction_file}", file=sys.stderr)
            return 2
        visualization_command.extend(["--junction-file", str(junction_file)])
    code = _run_stage("3/3 生成高德 HTML", visualization_command)
    if code:
        return code
    print(f"\n完成。打开地图：{html_path}")
    print(f"拆分数据：{split_dir / 'links.geojson'}")
    print(f"校验报告：{split_dir / 'validation_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
