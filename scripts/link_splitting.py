"""现有 GeoJSON 路链的细粒度拆分。

模块特意只依赖 Python 标准库：仓库已导出的 GeoJSON 可以在没有
GeoPandas/Shapely 的环境中再次处理。WGS84/GCJ-02 这类经纬度坐标会先
转换为与 ``process_guangdong_pbf.py`` 一致的 Web Mercator 米制坐标，再做
长度和插值计算；不会把经纬度角度直接当作距离。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import copy
import math
import os
from typing import Any, Iterable, Iterator, Sequence


Coordinate = tuple[float, float]
Feature = dict[str, Any]
Relationship = dict[str, Any]
EARTH_RADIUS_M = 6378137.0


class SplitError(ValueError):
    """输入路链无法在不破坏几何或 ID 约束的情况下拆分。"""


@dataclass(frozen=True)
class SplitConfig:
    """拆分参数；可由 .env/环境变量或 CLI 覆盖。"""

    max_link_length: float = 1000.0
    snap_tolerance_m: float = 0.5
    min_segment_length_m: float = 1.0
    validation_tolerance_m: float = 0.05
    metric_mode: str = "auto"  # auto | web-mercator | planar
    ramp_highway_values: tuple[str, ...] = (
        "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
    )
    skip_already_split: bool = True

    def __post_init__(self) -> None:
        if self.max_link_length <= 0:
            raise ValueError("MAX_LINK_LENGTH 必须大于 0")
        if self.snap_tolerance_m < 0 or self.min_segment_length_m < 0:
            raise ValueError("拆分容差不能为负数")
        if self.metric_mode not in {"auto", "web-mercator", "planar"}:
            raise ValueError("metric_mode 必须为 auto、web-mercator 或 planar")

    @classmethod
    def from_environment(cls) -> "SplitConfig":
        """读取项目既有的 KEY=VALUE 环境变量配置习惯。"""
        def number(name: str, default: float) -> float:
            raw = os.getenv(name)
            return default if raw in (None, "") else float(raw)

        ramps = os.getenv("RAMP_HIGHWAY_VALUES")
        return cls(
            max_link_length=number("MAX_LINK_LENGTH", 1000.0),
            snap_tolerance_m=number("LINK_SPLIT_SNAP_TOLERANCE_M", 0.5),
            min_segment_length_m=number("LINK_SPLIT_MIN_SEGMENT_LENGTH_M", 1.0),
            validation_tolerance_m=number("LINK_SPLIT_VALIDATION_TOLERANCE_M", 0.05),
            metric_mode=os.getenv("LINK_SPLIT_METRIC_MODE", "auto"),
            ramp_highway_values=tuple(
                item.strip() for item in ramps.split(",") if item.strip()
            ) if ramps else cls.ramp_highway_values,
            skip_already_split=os.getenv("LINK_SPLIT_SKIP_ALREADY_SPLIT", "true").lower()
            in {"1", "true", "yes", "on"},
        )


@dataclass
class SplitResult:
    features: list[Feature]
    relationships: list[Relationship]
    mapping: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_links: int = 0
    checked_sources: int = 0

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "checkedLinks": self.checked_links,
            "checkedSources": self.checked_sources,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def load_dotenv(path: str | os.PathLike[str] | None = None) -> None:
    """读取最简单的 .env 文件，遵循 fetch_gis_data.py 的环境变量优先规则。"""
    candidates = [path] if path else [".env", os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        with open(candidate, encoding="utf-8") as stream:
            for raw in stream:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip().strip("'\"")
                if key and not os.getenv(key):
                    os.environ[key] = value
        return


def resolve_id_field(features: Sequence[Feature], requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    properties = [feature.get("properties") or {} for feature in features]
    for field in ("link_id", "id"):
        if properties and all(row.get(field) not in (None, "") for row in properties):
            return field
    raise SplitError("找不到路链 ID 字段；请通过 --link-id-field 指定 link_id 或 id")


def _as_coordinate(value: Any) -> Coordinate:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise SplitError(f"无效坐标：{value!r}")
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise SplitError(f"无效坐标：{value!r}") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise SplitError(f"坐标必须是有限数值：{value!r}")
    return x, y


def _coordinate_mode(coords: Sequence[Coordinate], requested: str) -> str:
    if requested != "auto":
        return requested
    if all(-180 <= x <= 180 and -90 < y < 90 for x, y in coords):
        return "web-mercator"
    # 已投影为米制坐标的输入可以使用平面距离；不接受未知的角度坐标。
    return "planar"


def _to_metric(point: Coordinate, mode: str) -> Coordinate:
    if mode == "planar":
        return point
    lon, lat = point
    if not (-180 <= lon <= 180 and -85.05112878 < lat < 85.05112878):
        raise SplitError("经纬度坐标不在 Web Mercator 可投影范围内")
    x = EARTH_RADIUS_M * math.radians(lon)
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def _from_metric(point: Coordinate, mode: str) -> Coordinate:
    if mode == "planar":
        return point
    x, y = point
    return (
        math.degrees(x / EARTH_RADIUS_M),
        math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS_M)) - math.pi / 2),
    )


def _distance(first: Coordinate, second: Coordinate) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


def _same_point(first: Coordinate, second: Coordinate, tolerance: float = 1e-10) -> bool:
    return abs(first[0] - second[0]) <= tolerance and abs(first[1] - second[1]) <= tolerance


def geometry_to_coordinates(geometry: Any) -> list[Coordinate]:
    """把连续 LineString/MultiLineString 规范为一条有方向的坐标链。

    pyrosm 导出的 MultiLineString 常由连续的两点小段组成。若某条记录真的
    包含不连续多段，无法在不引入虚构道路的前提下把它当成一个 Link，因此报错。
    """
    if not isinstance(geometry, dict):
        raise SplitError("geometry 不是 GeoJSON 对象")
    kind, raw = geometry.get("type"), geometry.get("coordinates")
    if kind == "LineString":
        parts = [raw]
    elif kind == "MultiLineString":
        parts = raw
    else:
        raise SplitError(f"仅支持 LineString/MultiLineString，收到 {kind!r}")
    if not isinstance(parts, list) or not parts:
        raise SplitError("geometry 没有坐标")
    combined: list[Coordinate] = []
    for part in parts:
        if not isinstance(part, list) or len(part) < 2:
            raise SplitError("几何子段至少需要两个坐标")
        coords = [_as_coordinate(point) for point in part]
        if not combined:
            combined.extend(coords)
        elif _same_point(combined[-1], coords[0]):
            combined.extend(coords[1:])
        elif _same_point(combined[-1], coords[-1]):
            combined.extend(reversed(coords[:-1]))
        else:
            raise SplitError("MultiLineString 包含不连续子段，不能安全拆分")
    result: list[Coordinate] = []
    for point in combined:
        if not result or not _same_point(result[-1], point):
            result.append(point)
    if len(result) < 2:
        raise SplitError("geometry 去除重复点后不足两个坐标")
    return result


@dataclass(frozen=True)
class MeasuredLine:
    coordinates: tuple[Coordinate, ...]
    metric_coordinates: tuple[Coordinate, ...]
    measures: tuple[float, ...]
    mode: str

    @property
    def length(self) -> float:
        return self.measures[-1]

    @classmethod
    def from_geometry(cls, geometry: Any, metric_mode: str = "auto") -> "MeasuredLine":
        coords = geometry_to_coordinates(geometry)
        mode = _coordinate_mode(coords, metric_mode)
        metric = tuple(_to_metric(point, mode) for point in coords)
        measures = [0.0]
        for first, second in zip(metric, metric[1:]):
            length = _distance(first, second)
            if length <= 0:
                continue
            measures.append(measures[-1] + length)
        # geometry_to_coordinates has removed exact duplicate points. Still reject precision-degenerate lines.
        if len(measures) != len(metric) or measures[-1] <= 0:
            raise SplitError("geometry 的有效长度必须大于 0")
        return cls(tuple(coords), metric, tuple(measures), mode)

    def point_at(self, measure: float) -> Coordinate:
        if measure <= 0:
            return self.coordinates[0]
        if measure >= self.length:
            return self.coordinates[-1]
        for index in range(len(self.measures) - 1):
            start, end = self.measures[index], self.measures[index + 1]
            if measure <= end:
                ratio = (measure - start) / (end - start)
                first, second = self.metric_coordinates[index], self.metric_coordinates[index + 1]
                return _from_metric((first[0] + ratio * (second[0] - first[0]), first[1] + ratio * (second[1] - first[1])), self.mode)
        return self.coordinates[-1]

    def slice(self, start: float, end: float) -> list[Coordinate]:
        if end <= start:
            raise SplitError("切割区间必须有正长度")
        points = [self.point_at(start)]
        for measure, point in zip(self.measures[1:-1], self.coordinates[1:-1]):
            if start < measure < end:
                points.append(point)
        points.append(self.point_at(end))
        cleaned: list[Coordinate] = []
        for point in points:
            if not cleaned or not _same_point(cleaned[-1], point):
                cleaned.append(point)
        if len(cleaned) < 2:
            raise SplitError("切割后几何无效")
        return cleaned

    def measure_of_vertex(self, index: int) -> float:
        return self.measures[index]


def _grid_key(point: Coordinate, cell_size: float) -> tuple[int, int]:
    return math.floor(point[0] / cell_size), math.floor(point[1] / cell_size)


class EndpointIndex:
    """轻量端点网格索引，避免为每条 Link 逐一比对所有道路。"""

    def __init__(self, lines: Sequence[MeasuredLine], cell_size: float) -> None:
        self.lines = lines
        self.cell_size = max(cell_size, 0.01)
        self.grid: dict[tuple[int, int], list[tuple[int, int, Coordinate]]] = defaultdict(list)
        for link_index, line in enumerate(lines):
            for endpoint_index in (0, -1):
                point = line.metric_coordinates[endpoint_index]
                self.grid[_grid_key(point, self.cell_size)].append((link_index, endpoint_index, point))

    def nearby(self, point: Coordinate, tolerance: float) -> Iterator[tuple[int, int, Coordinate]]:
        key_x, key_y = _grid_key(point, self.cell_size)
        radius = max(1, math.ceil(tolerance / self.cell_size))
        for x in range(key_x - radius, key_x + radius + 1):
            for y in range(key_y - radius, key_y + radius + 1):
                yield from self.grid.get((x, y), ())

    def nearby_segment(self, first: Coordinate, second: Coordinate, tolerance: float) -> Iterator[tuple[int, int, Coordinate]]:
        """返回落在某线段包围盒附近的端点（再由调用方做精确投影）。"""
        low_x, high_x = sorted((first[0] - tolerance, second[0] + tolerance))
        low_y, high_y = sorted((first[1] - tolerance, second[1] + tolerance))
        first_key, last_key = _grid_key((low_x, low_y), self.cell_size), _grid_key((high_x, high_y), self.cell_size)
        yielded: set[tuple[int, int]] = set()
        for x in range(first_key[0], last_key[0] + 1):
            for y in range(first_key[1], last_key[1] + 1):
                for item in self.grid.get((x, y), ()):
                    identity = item[:2]
                    if identity not in yielded:
                        yielded.add(identity)
                        yield item


def _is_ramp(feature: Feature, config: SplitConfig) -> bool:
    properties = feature.get("properties") or {}
    road_type = str(properties.get("highway", properties.get("road_type", ""))).lower()
    if road_type in {value.lower() for value in config.ramp_highway_values}:
        return True
    # 兼容实际数据中已显式提供的布尔匝道字段，但不假定其一定存在。
    return any(properties.get(field) is True for field in ("is_ramp", "ramp", "isRamp"))


def find_forced_split_points(
    link_index: int,
    features: Sequence[Feature],
    lines: Sequence[MeasuredLine],
    endpoint_index: EndpointIndex,
    config: SplitConfig,
) -> list[float]:
    """找出当前 Link 的内部匝道/明显分合流点。

    现有 OSM 导出没有 Node 表，故以其他 Link 的端点贴合当前 Link 内部顶点
    表示拓扑节点。接入道路为 ``*_link`` 时立即强制拆分；同点有两条及以上
    外部道路端点时也视为明显分流/汇流。
    """
    line = lines[link_index]
    matches: list[tuple[float, int]] = []
    for segment_index, (first, second) in enumerate(zip(line.metric_coordinates, line.metric_coordinates[1:])):
        segment_length = _distance(first, second)
        if segment_length <= 0:
            continue
        for other_index, _endpoint, candidate in endpoint_index.nearby_segment(first, second, config.snap_tolerance_m):
            if other_index == link_index:
                continue
            dx, dy = second[0] - first[0], second[1] - first[1]
            ratio = ((candidate[0] - first[0]) * dx + (candidate[1] - first[1]) * dy) / (segment_length * segment_length)
            ratio = min(1.0, max(0.0, ratio))
            projected = (first[0] + ratio * dx, first[1] + ratio * dy)
            if _distance(candidate, projected) <= config.snap_tolerance_m:
                matches.append((line.measures[segment_index] + ratio * segment_length, other_index))
    matches.sort()
    found: list[float] = []
    cursor = 0
    while cursor < len(matches):
        measure = matches[cursor][0]
        connected: set[int] = set()
        while cursor < len(matches) and matches[cursor][0] - measure <= config.snap_tolerance_m:
            connected.add(matches[cursor][1])
            cursor += 1
        # Link 端点本来就是既有拓扑边界，不需要也不能在端点位置再切一次。
        if measure <= config.snap_tolerance_m or line.length - measure <= config.snap_tolerance_m:
            continue
        if any(_is_ramp(features[index], config) for index in connected) or len(connected) >= 2:
            found.append(measure)
    return found


def normalize_split_points(
    points: Iterable[float], total_length: float, config: SplitConfig,
    warnings: list[str] | None = None,
) -> list[float]:
    """去除端点、重复及会产生近零段的强制切点。"""
    normalized: list[float] = []
    for point in sorted(points):
        if point <= config.min_segment_length_m or total_length - point <= config.min_segment_length_m:
            if warnings is not None:
                warnings.append(f"忽略距 Link 端点不足 {config.min_segment_length_m:g}m 的拆分点")
            continue
        if normalized and point - normalized[-1] <= config.min_segment_length_m:
            if warnings is not None:
                warnings.append(f"合并间距不足 {config.min_segment_length_m:g}m 的拆分点")
            continue
        normalized.append(point)
    return normalized


def split_by_max_length(forced_points: Sequence[float], total_length: float, config: SplitConfig) -> list[float]:
    """在每个强制区间内均匀布点，避免留下很短的尾段。"""
    boundaries = [0.0, *forced_points, total_length]
    output = list(forced_points)
    for start, end in zip(boundaries, boundaries[1:]):
        interval = end - start
        count = max(1, math.ceil((interval - 1e-9) / config.max_link_length))
        output.extend(start + interval * index / count for index in range(1, count))
    return sorted(output)


class LinkIdGenerator:
    def __init__(self, existing_ids: Iterable[str]) -> None:
        self.used = {str(value) for value in existing_ids}

    def generate(self, source_link_id: str, segment_index: int) -> str:
        base = f"{source_link_id}__S{segment_index:03d}"
        candidate, suffix = base, 2
        while candidate in self.used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        self.used.add(candidate)
        return candidate


def _set_endpoint_properties(properties: dict[str, Any], start: Coordinate, end: Coordinate) -> None:
    values = {
        "start_lng": start[0], "start_lat": start[1], "end_lng": end[0], "end_lat": end[1],
        "startLng": start[0], "startLat": start[1], "endLng": end[0], "endLat": end[1],
    }
    for field, value in values.items():
        if field in properties:
            properties[field] = value


def inherit_link_attributes(
    source: Feature, link_id: str, source_link_id: str, segment_index: int,
    coordinates: Sequence[Coordinate], length_m: float, id_field: str,
) -> Feature:
    """复制所有业务属性，只覆盖拆分后必须更新的属性。"""
    properties = copy.deepcopy(source.get("properties") or {})
    properties["link_id"] = link_id
    if id_field != "link_id":
        properties[id_field] = link_id
    properties["source_link_id"] = source_link_id
    properties["segment_index"] = segment_index
    properties["length_m"] = round(length_m, 2)
    if "length" in properties:
        properties["length"] = round(length_m, 2)
    _set_endpoint_properties(properties, coordinates[0], coordinates[-1])
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {"type": "LineString", "coordinates": [[x, y] for x, y in coordinates]},
    }


def _relationship_id_generator(relationships: Sequence[Relationship]) -> Iterator[str]:
    used = {str(row.get("id")) for row in relationships if row.get("id") not in (None, "")}
    index = 1
    while True:
        candidate = f"SPLIT_REL_{index:09d}"
        index += 1
        if candidate not in used:
            used.add(candidate)
            yield candidate


def _relationship_fields(row: Relationship) -> tuple[str, str]:
    current = "currentLinkId" if "currentLinkId" in row else "current_link_id"
    following = "nextLinkId" if "nextLinkId" in row else "next_link_id"
    if current not in row or following not in row:
        raise SplitError("连通关系必须含 currentLinkId/current_link_id 和 nextLinkId/next_link_id")
    return current, following


def rebuild_topology(
    original_relationships: Sequence[Relationship], source_segments: dict[str, list[str]],
) -> list[Relationship]:
    """将关系的入边指向首段、出边改为末段，并新增子段之间的关系。"""
    result: list[Relationship] = []
    id_generator = _relationship_id_generator(original_relationships)
    for source in original_relationships:
        row = copy.deepcopy(source)
        current_field, next_field = _relationship_fields(row)
        current, following = str(row[current_field]), str(row[next_field])
        row[current_field] = source_segments[current][-1] if current in source_segments else current
        if following != "0":
            row[next_field] = source_segments[following][0] if following in source_segments else following
        result.append(row)
    # 每一个拆分链都必须有确定的内部前驱/后继。
    for source_id, ids in source_segments.items():
        for current, following in zip(ids, ids[1:]):
            result.append({
                "id": next(id_generator),
                "currentLinkId": current,
                "nextLinkId": following,
                "relationship_type": "split_internal",
                "source_link_id": source_id,
            })
    return result


def _is_already_split(feature: Feature) -> bool:
    properties = feature.get("properties") or {}
    return properties.get("source_link_id") not in (None, "") and properties.get("segment_index") not in (None, "")


def split_links(
    features: Sequence[Feature], relationships: Sequence[Relationship] | None = None,
    config: SplitConfig | None = None, id_field: str = "auto",
    forced_split_points_by_link: dict[str, list[float]] | None = None,
    preferred_split_points_by_link: dict[str, list[dict[str, Any]]] | None = None,
) -> SplitResult:
    """拆分 Link，并返回新 GeoJSON 要素、重建关系及原始 ID 映射。"""
    config = config or SplitConfig.from_environment()
    if not features:
        return SplitResult([], list(relationships or []), [])
    id_field = resolve_id_field(features, id_field)
    original_ids = [str((feature.get("properties") or {}).get(id_field)) for feature in features]
    if len(original_ids) != len(set(original_ids)):
        raise SplitError(f"输入 {id_field} 存在重复值，不能安全拆分")
    lines = [MeasuredLine.from_geometry(feature.get("geometry"), config.metric_mode) for feature in features]
    # 100m 网格兼顾长直线查询和高速路网的端点密度；精确判断仍使用 snap tolerance。
    endpoint_index = EndpointIndex(lines, max(config.snap_tolerance_m, 100.0))
    generated_ids = LinkIdGenerator(original_ids)
    output: list[Feature] = []
    source_segments: dict[str, list[str]] = {}
    mapping: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, (feature, line, source_id) in enumerate(zip(features, lines, original_ids)):
        if config.skip_already_split and _is_already_split(feature):
            # 默认幂等：再次处理已拆分的输出不再生成第二层子 Link。
            copied = copy.deepcopy(feature)
            copied.setdefault("properties", {})["length_m"] = round(line.length, 2)
            output.append(copied)
            source_segments[source_id] = [source_id]
            mapping.append({"source_link_id": source_id, "segment_link_ids": [source_id], "skipped": True})
            continue

        local_warnings: list[str] = []
        forced = normalize_split_points(
            find_forced_split_points(index, features, lines, endpoint_index, config),
            line.length, config, local_warnings,
        )
        # Confirmed OSM junctions are mandatory, even closer than the optional
        # near-zero threshold. Drop nearby geometric guesses in favor of real nodes.
        mandatory = sorted(set(point for point in (forced_split_points_by_link or {}).get(source_id, [])
                               if 1e-6 < point < line.length - 1e-6))
        if mandatory:
            forced = sorted([*mandatory, *(point for point in forced
                              if all(abs(point - node) > max(config.min_segment_length_m, 1e-5) for node in mandatory))])
        # Preserve previously published boundaries when geometry edits leave them on
        # this source line. Mandatory junctions always take precedence.
        anchors: dict[float, dict[str, Any]] = {}
        for anchor in sorted((preferred_split_points_by_link or {}).get(source_id, []), key=lambda row: row['measure']):
            point = float(anchor['measure'])
            if not config.min_segment_length_m < point < line.length - config.min_segment_length_m:
                continue
            if any(abs(point - existing) <= config.min_segment_length_m for existing in [*forced, *anchors]):
                continue
            forced.append(point)
            anchors[point] = anchor
        forced.sort()
        split_points = split_by_max_length(forced, line.length, config)
        boundaries = [0.0, *split_points, line.length]
        # 没有拆分需求时保持原 Link ID，不让正常短链的标识无谓变化。
        if len(boundaries) == 2:
            ids = [source_id]
        else:
            ids = [generated_ids.generate(source_id, segment_index) for segment_index in range(1, len(boundaries))]
        segments: list[str] = []
        source_root = str((feature.get("properties") or {}).get("source_link_id") or source_id)
        for segment_index, (start, end, link_id) in enumerate(zip(boundaries, boundaries[1:], ids), start=1):
            coordinates = line.slice(start, end)
            for position, boundary in ((0, start), (-1, end)):
                anchor = next((row for measure, row in anchors.items() if abs(measure - boundary) < 1e-6), None)
                if anchor and anchor['distanceM'] < 0.001:
                    coordinates[position] = tuple(anchor['coordinate'])
            child = inherit_link_attributes(
                feature, link_id, source_root, segment_index, coordinates, end - start, id_field,
            )
            output.append(child)
            segments.append(link_id)
        source_segments[source_id] = segments
        mapping.append({
            "source_link_id": source_root,
            "input_link_id": source_id,
            "segment_link_ids": segments,
            "forced_split_points_m": [round(point, 3) for point in forced],
        })
        warnings.extend(f"{source_id}: {warning}" for warning in local_warnings)

    rebuilt = rebuild_topology(list(relationships or []), source_segments)
    return SplitResult(output, rebuilt, mapping, warnings)


def rename_link_id(
    features: Sequence[Feature], relationships: Sequence[Relationship], old_id: str, new_id: str,
    id_field: str = "auto",
) -> tuple[list[Feature], list[Relationship]]:
    """安全改名一个 Link，并同步更新现有连通关系。"""
    if not new_id or not str(new_id).strip():
        raise SplitError("新 link_id 不能为空")
    resolved = resolve_id_field(features, id_field)
    old_id, new_id = str(old_id), str(new_id)
    ids = [str((feature.get("properties") or {}).get(resolved)) for feature in features]
    if old_id not in ids:
        raise SplitError(f"找不到 link_id={old_id}")
    if new_id in ids and new_id != old_id:
        raise SplitError(f"link_id={new_id} 已存在")
    new_features = copy.deepcopy(list(features))
    for feature in new_features:
        properties = feature.setdefault("properties", {})
        if str(properties.get(resolved)) == old_id:
            properties[resolved] = new_id
            properties["link_id"] = new_id
    new_relationships = copy.deepcopy(list(relationships))
    for row in new_relationships:
        current_field, next_field = _relationship_fields(row)
        if str(row[current_field]) == old_id:
            row[current_field] = new_id
        if str(row[next_field]) == old_id:
            row[next_field] = new_id
    return new_features, new_relationships


def update_mapping_link_id(mapping: Sequence[dict[str, Any]], old_id: str, new_id: str) -> list[dict[str, Any]]:
    """同步映射中的子链 ID；source_link_id 作为不可变追溯键不修改。"""
    updated = copy.deepcopy(list(mapping))
    for row in updated:
        row["segment_link_ids"] = [
            str(new_id) if str(value) == str(old_id) else value
            for value in row.get("segment_link_ids", [])
        ]
        if str(row.get("input_link_id")) == str(old_id):
            row["input_link_id"] = new_id
    return updated


def validate_split_result(
    input_features: Sequence[Feature], result: SplitResult, config: SplitConfig | None = None,
    id_field: str = "auto",
) -> ValidationReport:
    """检查长度、唯一 ID、源链长度守恒、连续性及关系引用。"""
    config = config or SplitConfig.from_environment()
    report = ValidationReport(warnings=list(result.warnings), checked_links=len(result.features))
    if not result.features:
        return report
    output_id_field = resolve_id_field(result.features, id_field)
    ids = [str((feature.get("properties") or {}).get(output_id_field)) for feature in result.features]
    if len(ids) != len(set(ids)):
        report.errors.append("输出 link_id 存在重复值")
    lines: dict[str, MeasuredLine] = {}
    for feature, link_id in zip(result.features, ids):
        try:
            line = MeasuredLine.from_geometry(feature.get("geometry"), config.metric_mode)
            lines[link_id] = line
            if line.length - config.max_link_length > config.validation_tolerance_m:
                report.errors.append(f"{link_id}: 长度 {line.length:.3f}m 超过 MAX_LINK_LENGTH")
            length_value = (feature.get("properties") or {}).get("length_m")
            if length_value not in (None, "") and abs(float(length_value) - line.length) > 0.02:
                report.errors.append(f"{link_id}: length_m 与 Geometry 长度不一致")
        except (SplitError, TypeError, ValueError) as exc:
            report.errors.append(f"{link_id}: Geometry/长度无效：{exc}")
    source_groups: dict[str, list[Feature]] = defaultdict(list)
    for feature in result.features:
        props = feature.get("properties") or {}
        source = props.get("source_link_id")
        if source in (None, ""):
            report.errors.append(f"{props.get(output_id_field)}: 缺少 source_link_id")
            continue
        source_groups[str(source)].append(feature)
    # 输入本身可能已经是一次拆分的输出。按 source 聚合而非只保留最后一段，
    # 可使默认的“跳过已拆分数据”保持幂等并仍通过长度守恒检查。
    original_lengths: dict[str, float] = defaultdict(float)
    for feature in input_features:
        props = feature.get("properties") or {}
        source = str(props.get("source_link_id") or props.get(resolve_id_field(input_features, id_field)))
        try:
            original_lengths[source] += MeasuredLine.from_geometry(feature.get("geometry"), config.metric_mode).length
        except SplitError as exc:
            report.errors.append(f"原始 {source}: Geometry 无效：{exc}")
    for source, children in source_groups.items():
        report.checked_sources += 1
        ordered = sorted(children, key=lambda item: int((item.get("properties") or {}).get("segment_index", 0)))
        positions = [int((item.get("properties") or {}).get("segment_index", 0)) for item in ordered]
        if positions != list(range(1, len(ordered) + 1)):
            report.errors.append(f"{source}: segment_index 必须从 1 连续递增")
        child_ids = [str((item.get("properties") or {}).get(output_id_field)) for item in ordered]
        for before, after in zip(child_ids, child_ids[1:]):
            if before in lines and after in lines and _distance(lines[before].metric_coordinates[-1], lines[after].metric_coordinates[0]) > config.snap_tolerance_m:
                report.errors.append(f"{source}: {before} 与 {after} Geometry 不连续")
        if source in original_lengths:
            children_length = sum(lines[link_id].length for link_id in child_ids if link_id in lines)
            if abs(children_length - original_lengths[source]) > max(config.validation_tolerance_m, original_lengths[source] * 1e-7):
                report.errors.append(f"{source}: 子链长度和与原链长度不守恒")
    valid_ids = set(ids)
    for row in result.relationships:
        try:
            current_field, next_field = _relationship_fields(row)
        except SplitError as exc:
            report.errors.append(f"关系记录无效：{exc}")
            continue
        if str(row[current_field]) not in valid_ids:
            report.errors.append(f"关系 currentLinkId={row[current_field]} 不存在")
        if str(row[next_field]) != "0" and str(row[next_field]) not in valid_ids:
            report.errors.append(f"关系 nextLinkId={row[next_field]} 不存在")
    return report
