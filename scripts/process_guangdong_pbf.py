#!/usr/bin/env python3
"""读取广东 OSM PBF，提取可驾驶路网并导出 GIS/路链文件。

依赖：pyrosm、geopandas、pandas。安装：python3 -m pip install pyrosm geopandas pandas
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BASE_DIR / "outputs/guangdong"
HIGHWAY_TYPES = {
    "motorway", "motorway_link",
}


def load_env() -> None:
    """读取项目目录 .env；已有非空环境变量优先。"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and (key not in os.environ or not os.environ[key]):
            os.environ[key] = value


def endpoint(geometry: object, which: str) -> tuple[float, float] | None:
    """兼容 LineString、MultiLineString，提取整条几何的首/末坐标。"""
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    geom_type = getattr(geometry, "geom_type", "")
    if geom_type == "LineString":
        coordinates = list(geometry.coords)
        return coordinates[0 if which == "start" else -1][:2] if coordinates else None
    if geom_type == "MultiLineString":
        parts = [part for part in geometry.geoms if not part.is_empty]
        if not parts:
            return None
        selected = parts[0] if which == "start" else parts[-1]
        coordinates = list(selected.coords)
        return coordinates[0 if which == "start" else -1][:2] if coordinates else None
    # 极少数异常几何：尝试使用边界点，不让单条坏记录中断整个批处理。
    boundary = getattr(geometry, "boundary", None)
    if boundary is not None and not boundary.is_empty and hasattr(boundary, "geoms"):
        points = list(boundary.geoms)
        point = points[0 if which == "start" else -1] if points else None
        return (point.x, point.y) if point is not None else None
    return None


def parse_args() -> argparse.Namespace:
    load_env()
    parser = argparse.ArgumentParser(description="处理广东 OSM PBF 并生成道路路链文件。")
    parser.add_argument(
        "--pbf",
        type=Path,
        default=Path(os.getenv("PBF_FILE", str(BASE_DIR / "data/pbf/guangdong-260921.osm.pbf"))),
        help="输入 .osm.pbf 文件；默认读取 .env 中的 PBF_FILE。",
    )
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("PBF_OUTPUT_DIR", str(DEFAULT_OUTPUT))), help="输出目录。")
    parser.add_argument("--output-prefix", default="guangdong", help="输出文件名前缀；默认 guangdong。")
    parser.add_argument("--link-id-prefix", default="OSM_GD", help="生成的 Link ID 前缀；默认 OSM_GD。")
    parser.add_argument(
        "--highway",
        nargs="+",
        default=sorted(HIGHWAY_TYPES),
        help="要保留的 highway 类型，默认仅保留 motorway 和 motorway_link。",
    )
    parser.add_argument("--all-drivable", action="store_true", help="保留 pyrosm 判定的全部可驾驶道路。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.output_prefix or any(char in args.output_prefix for char in ("/", "\\", ".")):
        print("--output-prefix 必须是不含路径分隔符或点号的文件名前缀。", file=sys.stderr)
        return 2
    if not args.link_id_prefix or not args.link_id_prefix.strip():
        print("--link-id-prefix 不能为空。", file=sys.stderr)
        return 2
    if not args.pbf.is_file():
        print(f"找不到 PBF 文件：{args.pbf}", file=sys.stderr)
        return 2
    try:
        from pyrosm import OSM
    except ImportError:
        print("缺少依赖，请先执行：python3 -m pip install pyrosm geopandas pandas", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"读取：{args.pbf}")
    osm = OSM(str(args.pbf))
    roads = osm.get_network(network_type="driving", nodes=False)
    if roads is None or roads.empty:
        print("PBF 中没有读取到可驾驶道路。", file=sys.stderr)
        return 1

    if not args.all_drivable and "highway" in roads.columns:
        roads = roads[roads["highway"].isin(args.highway)].copy()
    if roads.empty:
        print("筛选后没有道路，请检查 --highway 参数。", file=sys.stderr)
        return 1

    # OSM 原始坐标通常为 WGS84；保留原始 OSM 字段，并生成便于后续分析的稳定路链编号。
    roads = roads.reset_index(drop=True)
    source_id = roads["id"].astype(str) if "id" in roads.columns else roads.index.astype(str)
    roads.insert(0, "link_id", args.link_id_prefix + "_" + source_id + "_" + roads.index.astype(str))
    roads["source"] = "OpenStreetMap"
    roads["coordinate_system"] = "EPSG:4326 (WGS84)"

    # 从 LineString 提取起终点，形成接近现有 GIS Link 表的字段。
    starts = roads.geometry.apply(lambda g: endpoint(g, "start"))
    ends = roads.geometry.apply(lambda g: endpoint(g, "end"))
    roads["start_lng"] = starts.apply(lambda point: point[0] if point else None)
    roads["start_lat"] = starts.apply(lambda point: point[1] if point else None)
    roads["end_lng"] = ends.apply(lambda point: point[0] if point else None)
    roads["end_lat"] = ends.apply(lambda point: point[1] if point else None)
    # 先投影到米制坐标系再计算长度，避免在经纬度坐标上直接把角度当米。
    metric_roads = roads.to_crs("EPSG:3857") if roads.crs else roads
    roads["length_m"] = metric_roads.geometry.length.round(2)

    geojson_path = args.output_dir / f"{args.output_prefix}_roads.geojson"
    gpkg_path = args.output_dir / f"{args.output_prefix}_roads.gpkg"
    csv_path = args.output_dir / f"{args.output_prefix}_links.csv"
    roads.to_file(geojson_path, driver="GeoJSON")
    roads.to_file(gpkg_path, layer="roads", driver="GPKG")
    csv_columns = [
        column for column in (
            "link_id", "id", "name", "ref", "highway", "oneway", "lanes",
            "maxspeed", "surface", "length_m", "start_lng", "start_lat", "end_lng", "end_lat",
        ) if column in roads.columns
    ]
    roads[csv_columns].drop(columns=["geometry"], errors="ignore").to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"完成：{len(roads)} 条道路")
    print(f"GeoJSON: {geojson_path}")
    print(f"GeoPackage: {gpkg_path}")
    print(f"路链 CSV: {csv_path}")
    print("注意：这是 OSM 路网，不包含收费门架、收费单元或 ETC 实时数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
