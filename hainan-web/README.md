# 海南路链 Vue 网页

Vue 3 + Vite 单页应用，嵌入当前海南路网、OSM 有向拓扑及校验报告。页面直接展示路链列表、地图和属性详情，不显示出入口图层、顶栏、顶部标题或统计卡片。

## 启动

在本项目的 `路链处理` 目录运行：

```bash
npm --prefix hainan-web install
npm --prefix hainan-web run dev -- --port 5173
```

访问 http://127.0.0.1:5173/ 。也可进入 `hainan-web` 后使用 `npm install`、`npm run dev`。

## 功能

- 高德底图与真实路链叠加，显示时采用现有转换函数产生的 GCJ-02 坐标。
- 无外部地图服务时提供 WGS84 本地路网视图，支持缩放、平移、搜索和选择。
- 按名称、路线编号、路链 ID / 原链 ID 搜索，按主线、匝道、路线、桥梁或隧道筛选。
- 端点和方向箭头开关；为避免全域视图密集覆盖，端点在 10 级以上、箭头在 11 级以上显示。
- 查看路链属性、原链 ID、拆分段序号；点击拆分前后段可跳转定位。
- 在每条路链详情中展开“路链 GIS 点”，按折线顺序查看起点、中间点和终点的经纬度；可切换 WGS84 / GCJ-02，并复制当前坐标系下的点表。点表直接读取该路链的几何坐标，导出的 GeoJSON 仍通过 `geometry.coordinates` 保存原始 WGS84 点。
- 导出当前筛选结果为 WGS84 GeoJSON；出口文件不包含内部 GCJ-02 缓存。
- 显示项目现有拆分校验报告，适配桌面与手机布局。
- 在本地开发或预览服务中添加、编辑、删除选中的路链，并自动重算拆分、拓扑与编号。

数据口径：路链长度沿用原有拆分流程的 `length_m`，不是重新测量的里程；双向道路分别计入累计长度。OSM 相邻关系包含内部拆分和共享节点确认的跨原链连接，按通行方向生成，尚未包含转向限制与非高速道路。

## 更新数据

查看地图只需已有数据；点击“重新生成”需要本地 Python 3，沿用项目标准库脚本，不重新调用业务 API：

```bash
npm --prefix hainan-web run data
npm --prefix hainan-web run build
```

`data` 命令优先读取页面最近生成的 `outputs/hainan/generated/`；尚未使用页面生成时读取原有 `outputs/hainan/split/`，生成 `public/data/hainan.json`。所有有值的源属性均保留。

## 高德配置

默认仅读取上级项目 `.env` 中的 `AMAP_KEY` 和 `AMAP_SECURITY_CODE`。可将 `.env.example` 复制为 `.env.local`，使用 `VITE_AMAP_KEY`、`VITE_AMAP_SECURITY_CODE` 覆盖。必须是高德 Web 端 JS API 凭据，域名限制应包含实际访问域名。未配置 Key 或 SDK 网络加载失败时仍可查看本地路网。

开发模式沿用高德的明文安全密钥接入方式，便于本机调试。正式构建仅把 Web 端 Key 发给浏览器，安全密钥不进入构建文件；高德请求通过同源 `/_AMapService` 代理转发。Cloudflare Pages 直接上传可使用构建目录中的 `_worker.js` 和项目 Secret `AMAP_SECURITY_CODE`；自己的服务器也可配置同名代理。项目的业务接口 `API_APP_ID`、`API_APP_SECRET` 不会暴露给网页。完整步骤见 [分享与高德底图部署说明](../docs/share_demo_with_amap.md)。

## 静态构建

```bash
npm --prefix hainan-web run build
npm --prefix hainan-web run preview -- --port 4173
```

`dist/` 包含完整静态网页与海南数据，可由普通 HTTP 静态服务器托管。使用相对资源路径，支持子目录部署。不要直接双击 `dist/index.html`，浏览器会限制本地文件的模块脚本及数据读取。

## 结构

- `src/App.vue`：搜索筛选、列表、统计、详情、校验报告与导出。
- `src/components/RoadMap.vue`：Canvas 路链绘制、命中检测、地图定位和高德 SDK 对接。
- `scripts/prepare_data.py`：复用项目坐标转换函数，生成嵌入数据。
- `vite.config.js`：Vue 编译与地图配置白名单。

## 上下行标注

新增上下行筛选与详情标注。现有 G98 主线中有 1,377 条上行、1,379 条下行，均明确标为“推断”；其他路线和匝道保留待确认，79 条双向路链不赋予单一上下行。标注来自本地 PBF 路线关系、主线拓扑与公开方向基准，使用 `direction_annotation` 属性，不修改源数据。依据、范围、局限及检查方法见 [方向标注说明](../docs/direction_notes.md)。

## 接口数据关联

先按整条 G9811 对照主线，再逐个匝道收费单元匹配。当前 124 条业务路链通过严格空间检查，对应 207 条地图路链，其中 144 段显示接口空间关联的上下行方向。地图保留完整路网，先导路段以蓝色标注；支持业务编号/单元名称/桩号搜索、门架及业务连通关系查看。结果属于待复核的空间匹配，详见 [关联依据与对照报告](../docs/association_notes.md)。

## 路链项目编号与高亮

网页路链使用 `HN-路线-类型-六位序号`，主线类型为 `M`，匝道为 `R`，未标注路线为 `UN`。原链编号使用 `HN-SRC-六位序号`。已有编号由 `outputs/identifiers/link_id_registry.json` 保持稳定，完整对照保存在同目录的 `link_id_mapping.csv`。规则见 [编号说明](../docs/link_numbering.md)。

关联路段正常显示为蓝色，点击选中后恢复更粗的黄色高亮；其他道路仍显示。列表、详情、复制和相邻段跳转均使用项目编号，原 OSM 标识保留在源属性中。

## 页面重新生成

左侧“路链最大长度”可输入 100–10,000 m。重新生成时，先从 `outputs/hainan/source/hainan_roads.geojson` 的 4,452 条原始道路和本地编辑出发，按同路线、同方向的连续高速主线组成道路链；G9811 的 476 条主线原始段形成 19 条链，所有路线加匝道及本地编辑当前得到 1,790 条待切分源链。桥隧、车道数等属性变化保留在 `source_sections`，不会阻断合并；匝道接入、分岔和其他共享 OSM 节点仍强制切开，然后在这些切点之间按最大长度均匀拆分。完成长度、连续性、编号及关系校验后，重算上下行和本地接口关联。页面成功后自动更新地图；长度采用 Web Mercator 米制计算，这是每段上限，实际长度可能更短。

生成时继续显示已有路网，失败时保留原快照。生成服务一次执行一个任务，重复提交会被拒绝；刷新页面可恢复查看正在执行的任务。改变切分边界会分配新的路链编号，恢复同一边界时复用已有编号，原链编号保持一致。

生成结果保存在 `outputs/hainan/generated/`，编号注册表及关联报告同步更新，原始输入和原 `split/` 输出保留。也可直接运行：

```bash
python3 hainan-web/scripts/generate_data.py --max-link-length 1000
```

## 编辑路链

本地 `dev` 或 `preview` 页面左侧可点“添加路链”；选中地图或列表中的路链后，右侧可点“编辑本段”或“删除本段”。新增和修改通过每行一个 `经度, 纬度` 的 WGS84 GIS 点来绘制折线，至少两个点。编辑已拆分路链时，起终点必须保持在原位置（容差 0.5 m），中间点可调整；名称、路线编号、道路类型、通行方向、车道数和限速会同步应用到它所属的原链。删除只移除当前选中的拆分段，中间删除时两侧成为独立原链。

保存后自动重新切分并校验。受编辑影响的原链优先复用旧切点；未变几何尽量保留原有项目路链编号。几何改变的段会分配新编号，新建原链获得新的 `HN-SRC-` 编号。切点超过当前最大长度限制或不再位于编辑后的道路上时会重算；拓扑仍按现有 OSM 共享节点规则确认。编辑记录在 `outputs/hainan/edits/source_overrides.json`，原始 `source/hainan_roads.geojson` 不会被覆盖。生成失败时页面继续展示上一版数据。

静态部署只提供查看功能；编辑需要运行本地 Python 生成服务。可用 `--edit-stdin --dry-run` 通过标准输入传入单个 JSON 编辑请求进行试算，不发布数据。

本地 `npm run dev` 和 `npm run preview` 均支持生成；纯静态托管只能查看已生成的数据，不提供 Python 生成服务。`server/generation.js` 提供本地生成任务接口，`scripts/generate_data.py` 管理切分、校验和结果发布。

## 导出当前路链

运行 `python3 hainan-web/scripts/export_links.py`，可将当前网页快照导出到 `outputs/hainan/exports/hainan_links_current.geojson`。文件保留项目路链编号、WGS84 几何与业务关联；省略原始 OSM 道路/节点 ID，并补充 `gis_points` 完整有序点列表、GIS 点数、起终点坐标、前后相邻路链编号及中文道路类型/方向。每条路链的 `relationships.incoming` / `relationships.outgoing` 分别列出驶入、驶出的完整关系，不再单列顶层关系数组。`highway_name` 优先取路段自身的高速名称；当同一 `ref` 主线名称高度一致时才推定，其他留空并以 `highway_name_basis` 标注依据。路链数据更新后重新运行即可刷新导出文件。

字段解释、连通关系用法及读取示例见[海南路链 GeoJSON 数据说明](../docs/hainan_links_export_guide.md)。

要素详情默认展示名称、项目编号、长度、上下行、收费单元与桩号，以及前后段跳转；接口完整属性、门架、方向依据和源属性均折叠保留。

## OSM 跨原链拓扑

重新生成时从同源 PBF 恢复共享节点，必要时在合并后的源链内部增加切点，再建立有向连接。详情显示“驶入 / 驶出”，并标记内部或跨原链关系。当前 500 m 配置下共有 9,003 条路链、9,483 条有向关系，其中 2,252 条跨合并源链关系。拓扑依据、边界及输出见 [OSM 拓扑说明](../docs/osm_topology.md)。
