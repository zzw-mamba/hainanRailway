# OSM 跨原链道路拓扑

此前页面的相邻关系只覆盖同一原链的拆分子段。现已从同源海南 PBF 的 Way.refs 和 Node 坐标恢复共享节点，在路链之间建立有向连接，包含跨原链连接以及按通行方向重建的内部连接。

## 连接规则

- 从 `data/pbf/hainan-260922.osm.pbf` 提取当前道路的节点引用；本次找到全部 4,452 条原始 Way、29,422 个道路节点。
- 用道路自己的 Way 节点定位端点，跨原链连接必须共享同一个 OSM 节点编号。坐标相近、同名或者平面交叉都不作为连接依据；桥梁属性变化的真实共享节点仍可相连。
- 共享节点位于原链内部时，在该位置强制切分，再执行最大长度切分。真实节点切点优先于原有几何投影猜测，必要时保留不足 1 m 的短段。
- `oneway=yes` 沿几何方向通行，`oneway=-1` 反向，`oneway=no` 建立两个方向；方向缺失的道路保留未知，不推定连接。
- 普通长度切点不属于 OSM 节点，其连接键限定在同一原链内部。禁止立即返回同一条路链的掉头关系。
- 关系保留 `currentOrientation`、`nextOrientation` 和 `osmNodeId`，支持汇入、分岔及双向道路。多个方向具有同一相邻编号时，网页去重显示。

## 本次 500 m 结果

| 项目 | 数量 |
|---|---:|
| 地图路链 | 10,690 |
| 有向连接关系 | 11,171 |
| 内部有向关系 | 6,256 |
| 跨原链有向关系 | 4,915 |
| 未解析的原链起终点 | 0 |
| 未切分的共享连接节点 | 0 |
| 通行方向未知的路链 | 10 |

原有 10,680 段之外增加了 10 段，用于保留真实连接节点。原始输入保留，几何仍沿原有道路切分。道路边界改变时遵循现有项目编号规则分配编号。GIS 关联保持 124 条业务路链，对应 232 条地图路链。

243 条路链无已确认驶入关系，248 条无已确认驶出关系。按方向逐一核对后共有 523 条道路需要关注，包括双向道路某一个方向缺连接的情况；这些不一定是坏数据，可能处于筛选路网边界，连接到未纳入数据的普通道路，或通行方向未知。

该结果描述当前道路集合的连通性，尚未解析 OSM 转向限制、车辆类别限制和非高速道路。因此不能直接作为完整导航规则使用。

## 页面与文件

详情“相邻路链”展示“驶入 / 驶出”，并标记“内部 / 跨原链”；点击编号会定位对应道路，仍保留完整路网显示。

- `hainan-web/public/data/hainan.json`：项目编号路链、完整关系与 `topologySummary`。
- `hainan-web/public/data/topology_report.json`：使用项目编号的完整拓扑报告及待核对路链。
- `outputs/hainan/generated/link_relationships.json`：最近生成的完整拓扑，使用该目录 GeoJSON 的来源编号。
- `outputs/hainan/generated/topology_report.json`：对应生成输出的拓扑报告。
- `scripts/osm_topology.py`：PBF 节点索引、共享节点切点及有向拓扑。

页面重新生成自动重建拓扑。仅更新网页数据可运行 `npm --prefix hainan-web run data`；它读取现有几何建立关系，不会再次切分道路。如果报告显示未切分的共享节点，应运行页面“重新生成”。

现有 GeoJSON 加同源 PBF 也可以生成完整关系：

```bash
python3 scripts/split_links.py \
  --input outputs/hainan/source/hainan_roads.geojson \
  --osm-pbf data/pbf/hainan-260922.osm.pbf \
  --output-dir outputs/hainan/topology_split \
  --max-link-length 500
```

`run_link_pipeline.py` 使用 PBF 输入时自动启用共享节点拓扑；普通 GeoJSON 未提供同源 PBF 时保留原有关系处理方式。
