# 原始 PBF 高速公路属性统计

统计对象是原始 PBF 中 `highway=motorway`（高速主线）和 `highway=motorway_link`（高速匝道）的 OSM Way。OSM 标签没有固定字段表，同一属性可能只存在于部分 Way。下列数字是标签出现的 Way 数量，而不是空值数量。

| 原始文件 | 主线 Way / 标签种类 | 匝道 Way / 标签种类 | 完整明细 |
| --- | ---: | ---: | --- |
| `data/pbf/hainan-260922.osm.pbf` | 2,783 / 33 | 1,669 / 26 | `outputs/hainan/pbf_highway_attributes.json` |
| `data/pbf/guangdong-260921.osm.pbf` | 33,134 / 456 | 21,985 / 360 | `outputs/guangdong/pbf_highway_attributes.json` |

## 海南主线：33 种原始 OSM 标签

`alt_name`, `bridge`, `covered`, `embankment`, `fixme`, `highway`, `lanes`, `layer`, `maxspeed`, `motorroad`, `name`, `name:en`, `name:nan`, `name:nan-Hans`, `name:nan-Latn-pehoeji`, `name:nan-Latn-tailo`, `name:zh`, `name:zh-Hans`, `name:zh-Hant`, `note`, `old_name`, `old_name:en`, `old_ref`, `oneway`, `ref`, `source`, `source:geometry`, `start_date`, `surface`, `toll`, `tunnel`, `tunnel:name`, `wikipedia`。

常用字段覆盖情况：`highway` 2,783、`oneway` 2,783、`ref` 2,756、`name` 2,586、`lanes` 1,965、`bridge` 1,292、`surface` 1,147、`toll` 624、`maxspeed` 271。`ref` 常见值有 `G98`、`G9811`、`G9813`；`maxspeed` 记录中主要为 `120` 和 `100`。

## 海南匝道：26 种原始 OSM 标签

`access`, `bridge`, `construction`, `destination`, `destination:ref`, `destination:street`, `disused:highway`, `embankment`, `foot`, `highway`, `junction:ref`, `lanes`, `layer`, `maxspeed`, `name`, `name:en`, `note`, `old_ref`, `oneway`, `ref`, `source`, `source:geometry`, `start_date`, `surface`, `toll`, `tunnel`。

常用字段覆盖情况：`highway` 1,669、`oneway` 1,659、`bridge` 323、`lanes` 277、`surface` 102、`destination` 32、`destination:ref` 33、`maxspeed` 6。匝道中 `name` 仅有 7 条，不能依赖名称识别匝道。

## PBF 本身的结构字段与脚本派生字段

每条 OSM Way 还具有 Way ID 和节点引用 `refs`；本批文件每条被统计的 Way 均带 `version`、`timestamp`、`changeset`、`uid` 和 `user_sid` 元数据。这些属于 PBF 结构或元数据，不是上面列出的 OSM 标签。

`link_id`、`length_m`、`start_lng`、`start_lat`、`end_lng`、`end_lat`、`coordinate_system` 等是本项目处理时新增的字段，并非原始 PBF 的标签。广东文件字段种类较多，包含大量语言变体、车道规则、限行、收费、匝道目的地等稀疏标签；完整的每字段覆盖数和前五个常见值见 JSON 明细。

复现统计：

```bash
python3 scripts/inspect_pbf_highways.py --input data/pbf/hainan-260922.osm.pbf --output outputs/hainan/pbf_highway_attributes.json
python3 scripts/inspect_pbf_highways.py --input data/pbf/guangdong-260921.osm.pbf --output outputs/guangdong/pbf_highway_attributes.json
```
