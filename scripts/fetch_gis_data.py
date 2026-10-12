#!/usr/bin/env python3
"""下载海南自由流基础 GIS 数据并转换为 CSV / GeoJSON。

认证信息只从环境变量读取：API_APP_ID、API_APP_SECRET。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "https://hainan-test.datasw.cn/bds/api/jsonrpc"
METHODS = {
    "gantry": "BDS_GANTRY_LIST",
    "unit": "BDS_UNIT_LIST",
    "link": "BDS_LINK_LIST",
    # 服务端实际方法名由用户确认；协议中的旧拼写不再作为默认值。
    "link_relationship": "BDS_LINKREL_LIST",
}
METHOD_ALIASES = {
    "link_relationship": (
        "BDS_LINKREL_LIST",
    ),
}
DATASETS = ("gantry", "unit", "link", "link_relationship")


def load_dotenv(path: Path | None = None) -> Path | None:
    """读取简单 KEY=VALUE 配置；非空环境变量优先。"""
    if path is None:
        configured_path = os.getenv("GIS_ENV_FILE")
        candidates = [
            Path(configured_path) if configured_path else None,
            Path.cwd() / ".env",
            Path(__file__).resolve().parents[1] / ".env",
        ]
        path = next((candidate for candidate in candidates if candidate and candidate.is_file()), None)
    if path is None or not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or (key in os.environ and os.environ[key] != ""):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value
    return path


class RpcError(RuntimeError):
    """JSON-RPC 或传输层错误。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载门架、收费单元、路链及路链连通关系，并导出 GIS 文件。"
    )
    parser.add_argument("--endpoint", default=os.getenv("GIS_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("GIS_OUTPUT_DIR", "outputs/gis_data")))
    parser.add_argument(
        "--version",
        default=None,
        help="指定基础数据版本；省略时先调用 BDS_BASE_VERSION 自动查询。",
    )
    parser.add_argument("--timeout", type=float, default=float(os.getenv("GIS_TIMEOUT", "30")), help="单个 HTTP 请求超时秒数。")
    parser.add_argument("--retries", type=int, default=int(os.getenv("GIS_RETRIES", "2")), help="失败后的重试次数。")
    parser.add_argument(
        "--with-link-relationship",
        action="store_true",
        default=os.getenv("GIS_FETCH_LINK_RELATIONSHIP", "false").lower() in ("1", "true", "yes", "on"),
        help="同时获取路链联通关系；默认跳过。",
    )
    parser.add_argument(
        "--allow-validation-errors",
        action="store_true",
        help="即使关联、坐标等完整性校验失败，仍以成功状态结束。",
    )
    return parser.parse_args()


def rpc_call(
    endpoint: str, app_id: str, app_secret: str, method: str, params: dict[str, Any],
    request_id: int, timeout: float, retries: int,
) -> dict[str, Any]:
    payload = json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "api-app-id": app_id,
            "api-app-secret": app_secret,
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
            response_data = json.loads(body)
            if not isinstance(response_data, dict):
                raise RpcError(f"{method} 返回的 JSON 根节点不是对象")
            if response_data.get("id") != request_id:
                raise RpcError(f"{method} 响应 id 与请求不一致")
            if "error" in response_data:
                error = response_data["error"]
                raise RpcError(f"{method} JSON-RPC 错误: {error}")
            if "result" not in response_data:
                raise RpcError(f"{method} 响应缺少 result")
            return response_data
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RpcError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(2 ** attempt)
    raise RpcError(f"调用 {method} 失败（已重试 {retries} 次）: {last_error}")


def atomic_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def records_from_response(name: str, response: dict[str, Any]) -> list[dict[str, Any]]:
    result = response["result"]
    if not isinstance(result, dict):
        raise RpcError(f"{name} 的 result 不是对象")
    records = result.get("result")
    if not isinstance(records, list):
        raise RpcError(f"{name} 的 result.result 不是列表")
    if not all(isinstance(item, dict) for item in records):
        raise RpcError(f"{name} 的 result.result 包含非对象记录")
    declared_total = result.get("totalCount")
    if declared_total is not None and declared_total != len(records):
        raise RpcError(f"{name} totalCount={declared_total}，实际返回 {len(records)} 条")
    return records


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for item in records for key in item))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in records:
            writer.writerow({key: "" if value is None else value for key, value in item.items()})


def coordinate(record: dict[str, Any], lng_key: str, lat_key: str) -> list[float] | None:
    try:
        lng, lat = float(record[lng_key]), float(record[lat_key])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90) or lng == 0 or lat == 0:
        return None
    return [lng, lat]


def feature_collection(records: list[dict[str, Any]], geometry_kind: str) -> dict[str, Any]:
    features = []
    for record in records:
        if geometry_kind == "point":
            geometry_coordinates = coordinate(record, "lng", "lat")
            geometry = {"type": "Point", "coordinates": geometry_coordinates} if geometry_coordinates else None
        else:
            start = coordinate(record, "startLng", "startLat")
            end = coordinate(record, "endLng", "endLat")
            geometry = {"type": "LineString", "coordinates": [start, end]} if start and end else None
        features.append({"type": "Feature", "properties": record, "geometry": geometry})
    return {
        "type": "FeatureCollection",
        "name": "gantry" if geometry_kind == "point" else geometry_kind,
        # 原协议仅明确门架为 GCJ-02；此处统一标注为待确认，避免误作 WGS84。
        "coordinateReference": "GCJ-02 (gantry confirmed; unit/link coordinate reference to verify)",
        "features": features,
    }


def validate(data: dict[str, list[dict[str, Any]]]) -> list[str]:
    errors: list[str] = []
    link_ids = {str(row.get("id")) for row in data["link"] if row.get("id") not in (None, "")}
    unit_ids = {str(row.get("id")) for row in data["unit"] if row.get("id") not in (None, "")}
    for name in data:
        ids = [str(row.get("id")) for row in data[name] if row.get("id") not in (None, "")]
        if len(ids) != len(set(ids)):
            errors.append(f"{name}: 存在重复 id")
    for row in data["gantry"]:
        if str(row.get("linkId")) not in link_ids:
            errors.append(f"gantry {row.get('id')}: linkId={row.get('linkId')} 不存在")
        if not coordinate(row, "lng", "lat"):
            errors.append(f"gantry {row.get('id')}: 经纬度无效")
    for row in data["link"]:
        if str(row.get("unitId")) not in unit_ids:
            errors.append(f"link {row.get('id')}: unitId={row.get('unitId')} 不存在")
        if not coordinate(row, "startLng", "startLat") or not coordinate(row, "endLng", "endLat"):
            errors.append(f"link {row.get('id')}: 起终点经纬度无效")
    for row in data.get("link_relationship", []):
        current, next_link = str(row.get("currentLinkId")), str(row.get("nextLinkId"))
        if current not in link_ids:
            errors.append(f"relationship {row.get('id')}: currentLinkId={current} 不存在")
        if next_link != "0" and next_link not in link_ids:
            errors.append(f"relationship {row.get('id')}: nextLinkId={next_link} 不存在")
        if row.get("direction") not in ("UP", "DOWN"):
            errors.append(f"relationship {row.get('id')}: direction 应为 UP 或 DOWN")
    return errors


def main() -> int:
    load_dotenv()
    args = parse_args()
    app_id = os.getenv("API_APP_ID")
    app_secret = os.getenv("API_APP_SECRET")
    if not app_id or not app_secret:
        print("缺少 API_APP_ID 或 API_APP_SECRET 环境变量。", file=sys.stderr)
        return 2
    if args.timeout <= 0 or args.retries < 0:
        print("--timeout 必须大于 0，--retries 不能小于 0。", file=sys.stderr)
        return 2
    try:
        base_response = rpc_call(args.endpoint, app_id, app_secret, "BDS_BASE_VERSION", {"version": "-1"}, 1, args.timeout, args.retries)
        base_result = base_response["result"]
        version = args.version or (base_result.get("currentVersion") if isinstance(base_result, dict) else None)
        if not version or not isinstance(version, str):
            raise RpcError("BDS_BASE_VERSION 未返回有效的 currentVersion")
        target = args.output_dir / version
        raw_dir, csv_dir, geojson_dir = target / "raw", target / "csv", target / "geojson"
        for directory in (raw_dir, csv_dir, geojson_dir):
            directory.mkdir(parents=True, exist_ok=True)
        atomic_json(raw_dir / "base_version.json", base_response)
        data: dict[str, list[dict[str, Any]]] = {}
        datasets_to_fetch = DATASETS if args.with_link_relationship else DATASETS[:3]
        if not args.with_link_relationship:
            print("已跳过 link_relationship（如需获取请加 --with-link-relationship）。")
        for request_id, name in enumerate(datasets_to_fetch, start=2):
            print(f"正在下载 {name}…")
            configured_relationship_method = os.getenv("GIS_LINK_RELATIONSHIP_METHOD")
            if name == "link_relationship" and configured_relationship_method:
                method_candidates = (configured_relationship_method,)
            else:
                method_candidates = METHOD_ALIASES.get(name, (METHODS[name],))
            response = None
            attempted_methods: list[str] = []
            for candidate_index, method in enumerate(method_candidates):
                attempted_methods.append(method)
                try:
                    response = rpc_call(args.endpoint, app_id, app_secret, method, {"version": version}, request_id, args.timeout, args.retries)
                    if candidate_index > 0:
                        print(f"提示：协议拼写 {method_candidates[0]} 未注册，已使用兼容方法 {method}。")
                    break
                except RpcError as exc:
                    # 协议原文将 RELATIONSHIP 拼成 RRLATIONSHIP；部分服务端只实现标准拼写。
                    if not (name == "link_relationship" and candidate_index == 0 and "-32601" in str(exc)):
                        raise
            if response is None:
                raise RpcError(f"{name} 未获得响应；已尝试方法: {', '.join(attempted_methods)}")
            atomic_json(raw_dir / f"{name}.json", response)
            data[name] = records_from_response(name, response)
            write_csv(csv_dir / f"{name}.csv", data[name])
        atomic_json(geojson_dir / "gantry.geojson", feature_collection(data["gantry"], "point"))
        atomic_json(geojson_dir / "unit.geojson", feature_collection(data["unit"], "unit"))
        atomic_json(geojson_dir / "link.geojson", feature_collection(data["link"], "link"))
        validation_errors = validate(data)
        report = {
            "version": version,
            "downloadedAt": datetime.now(timezone.utc).isoformat(),
            "coordinateReference": "GCJ-02 confirmed for gantry; verify unit/link before mixing with WGS84 data.",
            "counts": {name: len(rows) for name, rows in data.items()},
            "linkRelationshipFetched": args.with_link_relationship,
            "validationErrors": validation_errors,
        }
        atomic_json(target / "validation_report.json", report)
        atomic_json(args.output_dir / "latest.json", {"version": version, "path": str(target), "updatedAt": report["downloadedAt"]})
        print(f"已写入 {target}")
        print("记录数：" + "，".join(f"{name}={len(rows)}" for name, rows in data.items()))
        if validation_errors:
            print(f"完整性校验发现 {len(validation_errors)} 项问题，详见 {target / 'validation_report.json'}", file=sys.stderr)
            return 0 if args.allow_validation_errors else 1
        print("完整性校验通过。")
        return 0
    except RpcError as exc:
        print(f"获取失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
