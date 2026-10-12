# 海南路链 GeoJSON 数据说明

本文解释 [`hainan_links_current.geojson`](../outputs/hainan/exports/hainan_links_current.geojson) 的结构和字段。它由当前 Vue 网页快照 [`hainan.json`](../hainan-web/public/data/hainan.json) 导出，供 GIS 软件查看或供程序读取。导出脚本是 [`export_links.py`](../hainan-web/scripts/export_links.py)。本说明中的数量对应文件当前版本；网页重新生成路网或再次编辑后，应重新运行导出脚本并以新文件为准。

## 当前数据范围

| 项目 | 当前值 |
|---|---:|
| 路链要素 `features` | 10,691 条 |
| 拆分前原链 `generation.sourceLinks` | 4,453 条 |
| 有向连通关系 | 11,171 条 |
| 高速主线路链 | 8,338 条 |
| 高速匝道路链 | 2,353 条 |
| 单条路链的 GIS 点数 | 2–40 个 |
| 最大拆分长度配置 | 500 m |
| 当前编辑修订号 | 1 |

`generation.generatedAt` 是路网快照的生成时间，使用 UTC ISO 8601；它不是本 GeoJSON 文件的最后导出时间。最大拆分长度是上限，不表示每段都恰好为 500 m：原始道路端点、真实连接节点和需要保留的切点都可能形成更短的路链。

## 文件结构

顶层是一个 GeoJSON `FeatureCollection`：

```text
type: "FeatureCollection"
name: "海南路链数据"
generation: { ...生成参数与时间... }
features: [
  {
    type: "Feature",
    properties: { ...路链属性、GIS 点列表和连通关系... },
    geometry: { type: "LineString", coordinates: [[经度, 纬度], ...] }
  }, ...
]
```

每个 `Feature` 表示一条**拆分后的**路链。`geometry.coordinates` 按道路折线顺序连接各个点，坐标为 **WGS84，经度在前、纬度在后**。属性中的 `gis_points` 与这组坐标逐点相同，只是增加了从 1 开始的点序号和明确的字段名：

```json
"gis_points": [
  {"index": 1, "longitude": 110.0341221, "latitude": 18.5324053},
  {"index": 2, "longitude": 110.0354483, "latitude": 18.5337118}
]
```

上面仅展示前两个点。一条路链的完整点列表应读取对应 `Feature.properties.gis_points`；不要把示例中的两个点当作整条路链。地图用的 GCJ-02 缓存坐标未导出，导出文件中的几何统一使用 WGS84。

## 常用路链属性

| 属性路径 | 类型 | 含义 |
|---|---|---|
| `properties.link_id` | 字符串 | 项目路链编号，路链的主键，例如 `HN-G98-M-000879`。 |
| `properties.source_link_id` | 字符串 | 拆分前原链的项目编号，例如 `HN-SRC-000630`；同一原链的子段共享它。 |
| `properties.segment_index` | 整数 | 当前原链内的拆分顺序，不是整条高速的里程顺序。 |
| `properties.name` | 字符串，可缺失 | 原路段名称；可能是高速名，也可能是联络线、机场路等名称。 |
| `properties.ref` | 字符串，可缺失 | 道路路线编号，如 `G98`、`G9811`；共线时可能包含分号。 |
| `properties.highway` | 字符串 | `motorway` 为高速主线，`motorway_link` 为匝道。 |
| `properties.road_type_label` | 字符串 | `highway` 对应的中文类型。 |
| `properties.highway_name` | 字符串或 `null` | 可确认或有明确依据推定的所属高速名称；空值表示待确认。 |
| `properties.highway_name_basis` | 字符串 | 高速名称的填写依据，见下节。 |
| `properties.length_m` | 数值 | 当前拆分路链沿折线计算的长度，单位米。 |
| `properties.gis_point_count` | 整数 | 当前路链 GIS 点数，等于 `gis_points.length`。 |
| `properties.gis_points` | 对象数组 | 这条路链的**全部** GIS 点，按折线顺序列出 `index`、`longitude`、`latitude`。 |
| `properties.start_lng/start_lat` | 数值 | 第一个 GIS 点的经纬度。 |
| `properties.end_lng/end_lat` | 数值 | 最后一个 GIS 点的经纬度。 |
| `properties.oneway` | 字符串，可缺失 | `yes` 顺坐标方向单行、`-1` 逆坐标方向单行、`no` 双向；缺失时不要自行推断。 |
| `properties.direction_label` | 字符串 | 页面所显示的上下行文字。 |
| `properties.direction_annotation` | 对象 | 上下行代码、标注状态及依据。 |
| `properties.previous_link_ids` | 字符串数组 | 去重后的可驶入本段的相邻项目路链编号。 |
| `properties.next_link_ids` | 字符串数组 | 去重后的可从本段驶出的相邻项目路链编号。 |
| `properties.relationships` | 对象 | 逐条有向连通关系，分 `incoming` 和 `outgoing` 两组。 |

编号格式是 `HN-路线-类型-六位序号`，其中 `M` 表示主线、`R` 表示匝道、`UN` 表示路线编号未知。编号用于标识，不代表桩号、距离或上下行。项目原链编号与路链编号属于不同编号体系。完整规则见[海南路链编号规则](link_numbering.md)。

### 所属高速名称如何得出

导出时先检查路段自身的 `name`。明确含“高速”的名称直接写入 `highway_name`，依据记为 `路段名称`。对于缺少明确高速名称但带有 `ref` 的路段，仅当同一编号的已命名**主线**中某一高速名称至少出现 10 次，且占该编号所有已命名主线的 95% 以上，才按路线补齐，并记为 `同路线主线名称推定`。其余 `highway_name` 为 `null`，依据记为 `待确认`。

当前有 7,558 条来自路段自身名称，55 条按同路线主线名称推定，3,078 条待确认。项目将 `G9811` 原数据中的旧称统一显示为“海三高速”。大量匝道没有 `name` 或 `ref`，不会仅因为空间上靠近某条主线就填入高速名称。

### 上下行标注

`direction_annotation.code` 为 `UP`、`DOWN` 或空；`direction_annotation.status` 表示标注状态。当前状态包括 `inferred`（G98 主线推断）、`business_matched`（接口空间关联）、`unconfirmed` 和 `bidirectional`。`direction_label` 是便于展示的中文文字；它不是另一套独立方向数据。当前有 1,672 条上行推断、1,676 条下行推断、165 条采用接口空间关联方向、79 条双向，其余 7,099 条待确认。推断和空间关联都不应被当作已现场核实的运营方向，详情见[上下行标注依据](direction_notes.md)。

## 内嵌连通关系

每条路链的 `properties.relationships` 包含：

- `incoming`：其他路链驶入当前路链的关系；其中 `nextLinkId` 是当前路链编号。
- `outgoing`：当前路链驶向其他路链的关系；其中 `currentLinkId` 是当前路链编号。

关系方向统一是 `currentLinkId → nextLinkId`。例如当前路链 `HN-G98-M-000879` 的一条驶出关系为：

```json
{
  "currentLinkId": "HN-G98-M-000879",
  "nextLinkId": "HN-G98-M-000886",
  "relationship_type": "split_internal",
  "currentOrientation": "forward",
  "nextOrientation": "forward",
  "basis": "osm_shared_node",
  "source_link_id": "HN-SRC-000630"
}
```

| 关系字段 | 含义 |
|---|---|
| `currentLinkId` / `nextLinkId` | 当前段与下一段的项目编号，按可行驶方向排列。 |
| `relationship_type` | `split_internal` 表示同一原链内部连接；`osm_cross_source` 表示跨原链连接。 |
| `currentOrientation` / `nextOrientation` | 车辆经过各段时相对于 GIS 点顺序的 `forward` / `reverse`；**不是**上行/下行。 |
| `basis` | 连接建立的依据：`osm_shared_node` 表示共享 OSM 节点，`same_source_split` 表示同一原链的连续拆分段。 |
| `source_link_id` | 内部拆分关系所属的项目原链编号；跨原链关系通常不包含此字段。 |

当前 11,171 条关系中，6,256 条为内部连接，4,915 条为跨原链连接。每条非终止关系会分别出现在起始路链的 `outgoing` 和目标路链的 `incoming`；统计关系总数时**只汇总一侧**，否则会重复计数。`previous_link_ids` 和 `next_link_ids` 是便于查找的去重编号列表；需要通行方向、关系类型或依据时应读取完整的 `relationships`。

关系表示当前高速主线与匝道集合内、依据源数据确认的有向连接。它没有包含所有普通道路、OSM 转向限制或车辆类别限制，不能直接当作完整导航路由表。被移除的原始 OSM 节点 ID 不在本导出文件中。

## 其他可选属性

部分要素还包含 `lanes`（车道数）、`maxspeed`（限速）、`surface`（路面）、`bridge`（桥梁）、`tunnel`（隧道）等源属性。这些字段只在源数据有值时出现；缺失不等于“无”或“0”。`source` 标识 OpenStreetMap 或本地编辑来源，`manual_edit` 仅在已手动编辑的源链上出现。`timestamp`、`version`、`tags` 等为源数据元信息，不能当作此文件的导出时间。

通过空间检查的 232 条路链带有 `business_association`，可读取 `coverage`、`matches` 中的业务路链编号、收费单元名称、重叠长度、起终桩号及方向等。它是空间匹配结果，并非全部路链都有业务桩号；`coverage` 小于 1 时尤其不能把业务桩号直接当作本段完整的起终桩号。关联方法和限制见[接口关联依据](association_notes.md)。

本文件移除了原始 `id`、OSM 派生道路 ID、OSM 节点 ID 及路线关系 ID；`link_id`、`source_link_id` 和业务接口编号继续保留，因为它们分别用于识别路链、关联原链和追溯收费业务数据。

## 读取示例

Python：按项目编号读取一条路链的全部 GIS 点及前后连接。

```python
import json
from pathlib import Path

path = Path("outputs/hainan/exports/hainan_links_current.geojson")
collection = json.loads(path.read_text(encoding="utf-8"))
roads = {f["properties"]["link_id"]: f for f in collection["features"]}
road = roads["HN-G98-M-000879"]
props = road["properties"]

print(props["highway_name"], props["length_m"])
for point in props["gis_points"]:
    print(point["index"], point["longitude"], point["latitude"])
print("驶入：", props["previous_link_ids"])
print("驶出：", props["next_link_ids"])
print("驶出关系详情：", props["relationships"]["outgoing"])
```

GIS 软件可直接将文件作为 GeoJSON 线图层打开，几何来自 `geometry.coordinates`。`gis_points`、`relationships` 等为嵌套 JSON 属性；若属性表不能直接展开数组，应在程序中解析这些字段。无需用点列表重新连线，因为 GeoJSON 已包含同样的折线几何。

## 更新导出

在项目根目录运行：

```bash
python3 hainan-web/scripts/export_links.py
```

脚本读取当前 `hainan-web/public/data/hainan.json`，覆盖更新 `outputs/hainan/exports/hainan_links_current.geojson`，**不修改**原始 OSM 数据或网页快照。若刚在页面中添加、修改、删除或重新拆分了路链，先确认页面已生成新快照，再运行导出命令。
