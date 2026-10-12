#!/usr/bin/env python3
"""使用高德地图 JS API 生成道路路链交互式 HTML。"""

from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


PI = 3.141592653589793
AXIS = 6378245.0
EE = 0.00669342162296594323


def out_of_china(lon: float, lat: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def transform_lat(x: float, y: float) -> float:
    result = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * abs(x) ** 0.5
    result += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    result += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    result += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return result


def transform_lon(x: float, y: float) -> float:
    result = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * abs(x) ** 0.5
    result += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    result += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    result += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return result


def wgs84_to_gcj02(lon: float, lat: float) -> list[float]:
    """将 WGS84 坐标转换为高德使用的 GCJ-02 坐标。"""
    if out_of_china(lon, lat):
        return [lon, lat]
    d_lat = transform_lat(lon - 105.0, lat - 35.0)
    d_lon = transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = 1 - EE * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = d_lat * 180.0 / ((AXIS * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lon = d_lon * 180.0 / (AXIS / sqrt_magic * math.cos(rad_lat) * PI)
    return [lon + d_lon, lat + d_lat]


def convert_coordinates(value: object) -> object:
    """递归转换 GeoJSON coordinates 数组。"""
    if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        converted = wgs84_to_gcj02(float(value[0]), float(value[1]))
        return converted + list(value[2:])
    if isinstance(value, list):
        return [convert_coordinates(item) for item in value]
    return value


def convert_geojson_to_gcj02(geojson: dict) -> dict:
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        if "coordinates" in geometry:
            geometry["coordinates"] = convert_coordinates(geometry["coordinates"])
    return geojson


def iter_positions(value: object):
    """遍历 GeoJSON 中所有经纬度位置，兼容 Point/LineString/MultiLineString。"""
    if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        yield float(value[0]), float(value[1])
    elif isinstance(value, list):
        for item in value:
            yield from iter_positions(item)


def padded_map_bounds(*collections: dict) -> dict[str, float]:
    """按当前地图要素范围生成带少量边距的视野限制框。"""
    positions = [
        position
        for collection in collections
        for feature in collection.get("features", [])
        for position in iter_positions((feature.get("geometry") or {}).get("coordinates"))
    ]
    if not positions:
        positions = [(109.7, 19.2)]
    west = min(point[0] for point in positions)
    east = max(point[0] for point in positions)
    south = min(point[1] for point in positions)
    north = max(point[1] for point in positions)
    padding_lng = max(0.06, (east - west) * 0.08)
    padding_lat = max(0.06, (north - south) * 0.08)
    return {
        "west": west - padding_lng,
        "south": south - padding_lat,
        "east": east + padding_lng,
        "north": north + padding_lat,
        "centerLng": (west + east) / 2,
        "centerLat": (south + north) / 2,
    }


def load_env() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and not os.getenv(key):
            os.environ[key] = value


def configured_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


def main() -> None:
    load_env()
    import argparse

    parser = argparse.ArgumentParser(description="生成高德地图道路可视化 HTML")
    parser.add_argument(
        "--input-file",
        default=os.getenv("AMAP_INPUT_FILE", ""),
        help="GeoJSON 输入文件；默认使用 PBF_OUTPUT_DIR/guangdong_roads.geojson",
    )
    parser.add_argument(
        "--output-file",
        default=os.getenv("AMAP_OUTPUT_FILE", ""),
        help="HTML 输出文件；默认写入输入文件所在目录",
    )
    parser.add_argument("--junction-file", default="", help="可选：motorway_junction 出入口 Point GeoJSON")
    parser.add_argument("--title", default="道路路链地图", help="HTML 页面及地图面板标题")
    args = parser.parse_args()
    output_dir = configured_path(os.getenv("PBF_OUTPUT_DIR", "outputs/guangdong"))
    input_file = configured_path(args.input_file) if args.input_file else output_dir / "guangdong_roads.geojson"
    output_file = configured_path(args.output_file) if args.output_file else input_file.parent / "guangdong_roads_amap.html"
    amap_key = os.getenv("AMAP_KEY", "")
    security_code = os.getenv("AMAP_SECURITY_CODE", "")
    if not amap_key:
        raise SystemExit("缺少 AMAP_KEY，请将高德 Web 端 Key 写入 .env")
    if not input_file.exists():
        raise SystemExit(f"找不到 {input_file}，请先运行 process_guangdong_pbf.py 或检查 PBF_OUTPUT_DIR")

    geojson = convert_geojson_to_gcj02(json.loads(input_file.read_text(encoding="utf-8")))
    junction_file = configured_path(args.junction_file) if args.junction_file else None
    junctions = {"type": "FeatureCollection", "features": []}
    if junction_file:
        if not junction_file.is_file():
            raise SystemExit(f"找不到高速出入口 GeoJSON：{junction_file}")
        junctions = convert_geojson_to_gcj02(json.loads(junction_file.read_text(encoding="utf-8")))
    # JSON 嵌入 script 标签时避免意外终止 HTML。
    geojson_text = json.dumps(geojson, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    junction_text = json.dumps(junctions, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    map_bounds_text = json.dumps(padded_map_bounds(geojson, junctions), separators=(",", ":"))
    security_config = (
        f"window._AMapSecurityConfig={{securityJsCode:{json.dumps(security_code)}}};"
        if security_code else ""
    )
    page = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(args.title)} - 高德地图</title>
  <style>
    html, body, #map {{ width:100%; height:100%; margin:0; }}
    .panel {{ position:absolute; z-index:10; top:16px; left:16px; background:rgba(255,255,255,.95); padding:12px 16px; border-radius:8px; box-shadow:0 2px 12px #0002; font:14px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; }}
    .title {{ font-size:17px; font-weight:600; margin-bottom:8px; }}
    .legend {{ line-height:24px; }}
    .swatch {{ display:inline-block; width:28px; height:4px; margin-right:6px; vertical-align:middle; }}
    .tip {{ color:#666; margin-top:7px; font-size:12px; max-width:260px; }}
    .map-toggle {{ display:flex; align-items:center; gap:6px; margin-top:8px; font-size:13px; cursor:pointer; }}
    .map-toggle input {{ margin:0; }}
    .endpoint-dot {{ display:inline-block; width:9px; height:9px; border:2px solid white; border-radius:50%; box-shadow:0 0 0 1px #73808c; vertical-align:middle; margin-right:6px; }}
    .junction-dot {{ display:inline-block; width:10px; height:10px; border:2px solid white; border-radius:50%; background:#6a1b9a; box-shadow:0 0 0 1px #6a1b9a; vertical-align:middle; margin-right:6px; }}
    .hover-card {{ position:absolute; z-index:30; display:none; pointer-events:none; padding:7px 10px; border-radius:6px; background:rgba(17,34,51,.92); color:white; box-shadow:0 3px 12px #0005; font:12px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; white-space:nowrap; transform:translate(14px,-100%); }}
    .structure-tags {{ margin:6px 0; padding:6px 8px; border-radius:5px; background:#fff4dc; color:#805300; }}
  </style>
  {security_config}
  <script src="https://webapi.amap.com/maps?v=2.0&key={html.escape(amap_key)}&plugin=AMap.GeoJSON,AMap.Scale,AMap.ToolBar"></script>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <div class="title">{html.escape(args.title)}</div>
    <div class="legend">
      <div><span class="swatch" style="background:#e53935"></span>白色箭头表示通行方向</div>
      <div><span class="swatch" style="background:#fb8c00"></span>主要干道</div>
      <div><span class="swatch" style="background:#1976d2"></span>国省道</div>
      <div><span class="endpoint-dot" style="background:#13a46b"></span>路链起点</div>
      <div><span class="endpoint-dot" style="background:#f18832"></span>路链终点</div>
      <div><span class="endpoint-dot" style="background:#8354cc"></span>共用端点</div>
      <div><span class="junction-dot"></span>高速出入口</div>
    </div>
    <label class="map-toggle"><input id="toggle-endpoints" type="checkbox" checked />显示路链端点</label>
    <label class="map-toggle"><input id="toggle-junctions" type="checkbox" />显示高速出入口</label>
    <div class="tip">已转换 WGS84 → GCJ-02；点击道路查看属性。</div>
  </div>
  <div id="hover-card" class="hover-card"></div>
  <script>
    const roadData = {geojson_text};
    const junctionData = {junction_text};
    const mapBounds = {map_bounds_text};
    const colors = {{
      motorway: '#e53935', motorway_link: '#ef5350',
      trunk: '#fb8c00', trunk_link: '#ffb74d',
      primary: '#1976d2', primary_link: '#42a5f5',
      secondary: '#43a047', secondary_link: '#66bb6a'
    }};
    const safe = value => String(value == null ? '-' : value).replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[char]);
    function structureLabels(props) {{
      const labels = [];
      const tagged = value => value != null && String(value).trim() !== '' && String(value).toLowerCase() !== 'no';
      if (tagged(props.bridge)) labels.push(props.bridge === 'yes' ? '桥梁' : '桥梁 / ' + props.bridge);
      if (tagged(props.tunnel)) labels.push(props.tunnel === 'yes' ? '隧道' : '隧道 / ' + props.tunnel);
      if (tagged(props.covered)) labels.push('有顶棚');
      if (tagged(props.embankment)) labels.push('路堤');
      if (props.layer != null && String(props.layer) !== '' && Number(props.layer) !== 0) {{
        labels.push('道路层级 ' + (Number(props.layer) > 0 ? '+' : '') + props.layer);
      }}
      return labels;
    }}
    const hoverCard = document.getElementById('hover-card');
    const map = new AMap.Map('map', {{ zoom: 7, center: [mapBounds.centerLng, mapBounds.centerLat], viewMode: '2D' }});
    const directionArrow = document.createElement('canvas');
    directionArrow.width = directionArrow.height = 18;
    const arrowContext = directionArrow.getContext('2d');
    arrowContext.strokeStyle = '#ffffff';
    arrowContext.lineWidth = 5;
    arrowContext.lineCap = 'round';
    arrowContext.lineJoin = 'round';
    arrowContext.beginPath();
    arrowContext.moveTo(4, 14);
    arrowContext.lineTo(9, 5);
    arrowContext.lineTo(14, 14);
    arrowContext.stroke();
    map.addControl(new AMap.Scale());
    map.addControl(new AMap.ToolBar({{ position: 'RB' }}));
    if (!AMap.GeoJSON) {{
      throw new Error('AMap.GeoJSON 插件未加载，请检查高德 Key 或网络连接');
    }}
    const hoverHalo = new AMap.Polyline({{
      path: [], strokeColor: '#ffffff', strokeWeight: 14,
      strokeOpacity: .9, lineJoin: 'round', zIndex: 119,
    }});
    map.add(hoverHalo);
    hoverHalo.hide();
    let activeLine = null;
    function hideHover() {{
      if (activeLine) {{
        activeLine.setOptions(activeLine._normalStyle);
        activeLine = null;
      }}
      hoverHalo.hide();
      hoverCard.style.display = 'none';
    }}
    function placeHoverCard(event) {{
      if (!event || !event.lnglat) return;
      const pixel = map.lngLatToContainer(event.lnglat);
      hoverCard.style.left = pixel.x + 'px';
      hoverCard.style.top = pixel.y + 'px';
    }}
    const roads = new AMap.GeoJSON({{
      geoJSON: roadData,
      getPolyline: function(feature, lnglats) {{
        const props = feature.properties || {{}};
        const highway = props.highway || '';
        const isRamp = highway === 'motorway_link';
        const displayName = isRamp
          ? [props.name, props.ref].filter(value => value != null && String(value).trim() !== '').join(' · ') || '高速匝道'
          : (props.name || '未命名道路');
        const oneway = String(props.oneway || '').toLowerCase();
        const color = colors[highway] || '#78909c';
        const width = highway.startsWith('motorway') ? 8 : 7;
        const showForward = oneway !== '-1';
        const line = new AMap.Polyline({{ path: lnglats, strokeColor: color, strokeWeight: width, strokeOpacity: .85, lineJoin: 'round', zIndex: 10, showDir: showForward, dirColor: '#ffffff' }});
        line._normalStyle = {{ strokeColor: color, strokeWeight: width, strokeOpacity: .85, zIndex: 10, showDir: showForward, dirColor: '#ffffff' }};
        if (oneway === 'no' || oneway === '-1') {{
          map.add(new AMap.Polyline({{
            path: line.getPath().slice().reverse(), strokeColor: color, strokeWeight: width,
            strokeOpacity: .01, lineJoin: 'round', zIndex: 9, showDir: true,
            dirColor: '#ffffff', dirImg: directionArrow,
          }}));
        }}
        line.on('mouseover', function(event) {{
          if (activeLine && activeLine !== line) hideHover();
          activeLine = line;
          hoverHalo.setPath(line.getPath());
          hoverHalo.setOptions({{ strokeWeight: width + 10 }});
          hoverHalo.show();
          line.setOptions({{ strokeColor: '#00cfe8', strokeWeight: width + 5, strokeOpacity: 1, zIndex: 120 }});
          const structures = structureLabels(props);
          hoverCard.textContent = displayName + ' · ' + (props.link_id || '-') + ' · ' +
            (Number(props.length_m) || 0).toFixed(1) + ' m' +
            (structures.length ? ' · ' + structures.join('、') : '');
          hoverCard.style.display = 'block';
          placeHoverCard(event);
        }});
        line.on('mousemove', placeHoverCard);
        line.on('mouseout', function() {{ if (activeLine === line) hideHover(); }});
        line.on('click', function(e) {{
          const title = safe(displayName);
          const routeInfo = !isRamp && props.ref
            ? '<br>路线编号：' + safe(props.ref)
            : '';
          const structures = structureLabels(props);
          const structureInfo = structures.length
            ? '<div class="structure-tags"><b>特殊道路结构：</b>' + structures.map(safe).join('、') + '</div>'
            : '';
          const content = '<b>' + title + '</b>' +
            routeInfo + '<br>' +
            '路链编号：' + safe(props.link_id) + '<br>' +
            structureInfo +
            '<br>长度：' + (Number.isFinite(Number(props.length_m)) ? Number(props.length_m).toFixed(1) + ' m' : '-');
          new AMap.InfoWindow({{ content: content, offset: new AMap.Pixel(0, -8) }}).open(map, e.lnglat);
        }});
        return line;
      }}
    }});
    map.add(roads);
    const junctionMarkers = [];
    const junctionInfo = new AMap.InfoWindow({{ offset: new AMap.Pixel(0, -14) }});
    for (const feature of junctionData.features || []) {{
      const geometry = feature.geometry || {{}};
      const props = feature.properties || {{}};
      if (geometry.type !== 'Point' || !Array.isArray(geometry.coordinates)) continue;
      const position = geometry.coordinates;
      const marker = new AMap.CircleMarker({{
        center: position,
        radius: 9,
        fillColor: '#6a1b9a',
        fillOpacity: 1,
        strokeColor: '#ffffff',
        strokeOpacity: 1,
        strokeWeight: 2,
        zIndex: 130,
      }});
      marker.on('mouseover', function() {{ marker.setOptions({{ radius: 12 }}); }});
      marker.on('mouseout', function() {{ marker.setOptions({{ radius: 9 }}); }});
      marker.on('click', function() {{
        const title = props.name || (props.ref ? '高速出入口 ' + props.ref : '高速出入口');
        const details = [
          props.ref ? '出入口编号：' + safe(props.ref) : '',
          props.osm_node_id != null ? 'OSM 节点：' + safe(props.osm_node_id) : '',
        ].filter(Boolean).join('<br>');
        junctionInfo.setContent('<b>' + safe(title) + '</b>' + (details ? '<br>' + details : ''));
        junctionInfo.open(map, marker.getCenter());
      }});
      junctionMarkers.push(marker);
    }}
    const junctionToggle = document.getElementById('toggle-junctions');
    junctionToggle.disabled = junctionMarkers.length === 0;
    junctionToggle.addEventListener('change', event => {{
      if (event.target.checked) map.add(junctionMarkers);
      else map.remove(junctionMarkers);
    }});
    map.setFitView([roads, ...junctionMarkers]);
    map.setLimitBounds(new AMap.Bounds(
      [mapBounds.west, mapBounds.south],
      [mapBounds.east, mapBounds.north]
    ));
    // 共用坐标只显示一个点，但保留起点、终点两种角色，避免叠画掩盖连接处。
    const endpoints = new Map();
    function addEndpoint(lnglat, role) {{
      if (!Array.isArray(lnglat) || lnglat.length < 2) return;
      const key = Number(lnglat[0]).toFixed(7) + ',' + Number(lnglat[1]).toFixed(7);
      if (!endpoints.has(key)) endpoints.set(key, {{ lnglat: [lnglat[0], lnglat[1]], roles: 0 }});
      endpoints.get(key).roles |= role;
    }}
    for (const feature of roadData.features || []) {{
      const geometry = feature.geometry || {{}};
      const coordinates = geometry.coordinates || [];
      if (geometry.type === 'LineString' && coordinates.length >= 2) {{
        addEndpoint(coordinates[0], 1);
        addEndpoint(coordinates[coordinates.length - 1], 2);
      }} else if (geometry.type === 'MultiLineString' && coordinates.length) {{
        const first = coordinates.find(part => part.length);
        const last = [...coordinates].reverse().find(part => part.length);
        if (first && last) {{
          addEndpoint(first[0], 1);
          addEndpoint(last[last.length - 1], 2);
        }}
      }}
    }}
    function dotIcon(color) {{
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 16;
      const context = canvas.getContext('2d');
      context.beginPath();
      context.arc(8, 8, 5.5, 0, Math.PI * 2);
      context.fillStyle = color;
      context.fill();
      context.lineWidth = 2;
      context.strokeStyle = '#fff';
      context.stroke();
      return canvas.toDataURL('image/png');
    }}
    const endpointStyle = ['#13a46b', '#f18832', '#8354cc'].map(color => ({{
      url: dotIcon(color), size: new AMap.Size(16, 16), anchor: new AMap.Pixel(8, 8),
    }}));
    const endpointData = [...endpoints.values()].map(point => ({{
      lnglat: point.lnglat, style: point.roles - 1,
    }}));
    const endpointLayer = new AMap.MassMarks(endpointData, {{
      style: endpointStyle, zIndex: 121, opacity: .95, zooms: [3, 20],
    }});
    endpointLayer.setMap(map);
    document.getElementById('toggle-endpoints').addEventListener('change', event => {{
      endpointLayer.setMap(event.target.checked ? map : null);
    }});
    const roadCount = Array.isArray(roadData.features) ? roadData.features.length : 0;
    document.querySelector('.tip').textContent = '已加载 ' + roadCount + ' 条路链、' + endpoints.size + ' 个端点、' + junctionMarkers.length + ' 个高速出入口；悬停道路高亮，点击查看详情。';
  </script>
</body>
</html>'''
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(page, encoding="utf-8")
    print(f"高德地图 HTML 已生成：{output_file}")


if __name__ == "__main__":
    main()
