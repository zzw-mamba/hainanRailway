# 海南自由流 GIS 基础数据下载脚本

`scripts/fetch_gis_data.py` 根据《基础数据与感知数据通信协议 V1.0》下载基础 GIS 数据：门架、收费单元、路链与路链连通关系。它使用 Python 标准库，不需要安装第三方包。

## 一条命令完成路网处理与地图生成

`scripts/run_link_pipeline.py` 将本项目已有的 PBF 提取、路链拆分与高德 HTML 生成脚本串成一条流程。先在 `.env` 中配置 `AMAP_KEY`，处理 PBF 还需安装 `pyrosm geopandas pandas`：

```bash
python3 -m pip install pyrosm geopandas pandas
python3 scripts/run_link_pipeline.py \
  --input data/pbf/guangdong-260921.osm.pbf \
  --output-dir outputs/link_pipeline \
  --max-link-length 1000
```

如果已经有本项目导出的 WGS84 GeoJSON，可以从该文件开始，无需再次解析 PBF：

```bash
python3 scripts/run_link_pipeline.py \
  --input /path/to/guangdong_roads.geojson \
  --output-dir outputs/link_pipeline \
  --max-link-length 1000
```

命令运行成功后打开 `输出目录/links_amap.html`。`输出目录/source/` 保存 PBF 提取的道路与高速出入口点（`*_motorway_junctions.geojson`；PBF 输入时自动提取）；`输出目录/split/` 保存细粒度 GeoJSON、原链映射、连通关系和校验报告。拆分校验失败时流程停止，不生成新的 HTML。最大长度也可通过 `.env` 中的 `MAX_LINK_LENGTH` 配置；若有原始路链关系文件，可加 `--relationships 文件路径`。默认输入读取 `.env` 的 `PBF_FILE`。

## 配置与运行

脚本会自动读取当前工作目录或项目根目录下的 `.env`。也可以通过 `GIS_ENV_FILE` 指定配置文件路径。请先编辑其中的 `API_APP_ID` 和 `API_APP_SECRET`，凭据不能写入代码或提交到 Git：

脚本默认跳过路链连通关系接口，只下载门架、收费单元和路链。确认服务端方法名后，可使用 `--with-link-relationship` 恢复获取。启用后，脚本调用用户确认的服务端方法 `BDS_LINKREL_LIST`（协议原文的旧方法名不可用）。
如果中台提供了其他方法名，可在 `.env` 中设置 `GIS_LINK_RELATIONSHIP_METHOD` 覆盖自动尝试列表。PDF 只规定了接口名称，并不能改变服务端实际注册的方法；若所有候选方法均返回 `-32601`，需要让中台确认真实方法名。

## 处理广东 OSM PBF

项目目录中的 `guangdong-260921.osm.pbf` 可以用以下脚本处理：

要选择其他 PBF，只需修改 `.env`：

```env
PBF_FILE=另一个文件.osm.pbf
PBF_OUTPUT_DIR=另一个输出目录
```

也可以临时用命令行覆盖配置：

```bash
python3 scripts/process_guangdong_pbf.py --pbf ./另一个文件.osm.pbf --output-dir ./另一个输出目录
```

```bash
python3 -m pip install pyrosm geopandas pandas
python3 scripts/process_guangdong_pbf.py
```

如果运行 Kepler.gl 时出现 `No module named 'pkg_resources'`，这是当前 Kepler.gl 版本仍依赖旧版 `pkg_resources`。请安装兼容版：

```bash
python3 -m pip install 'setuptools<81'
```

## 使用高德地图可视化

将高德 Web 端 JS API Key 写入 `.env`：

```env
AMAP_KEY=你的高德Key
AMAP_SECURITY_CODE=你的安全密钥
```

然后运行：

```bash
python3 scripts/visualize_guangdong_amap.py
```

脚本默认读取 `.env` 中 `PBF_OUTPUT_DIR` 下的 `guangdong_roads.geojson`，并在同一目录生成 `guangdong_roads_amap.html`。也可通过 `AMAP_INPUT_FILE`、`AMAP_OUTPUT_FILE` 或命令行参数覆盖：

```bash
python3 scripts/visualize_guangdong_amap.py \
  --input-file hainan/guangdong_roads.geojson \
  --output-file hainan/guangdong_roads_amap.html
```

用浏览器打开生成的 HTML 即可看到高德底图、彩色道路、缩放控件以及道路属性弹窗。悬停路链会高亮并显示编号、名称和长度；每条路链的起点、终点以不同颜色打点，重合的起终点合并为紫色标记。面板可切换端点显示。脚本会在嵌入 HTML 前将 OSM 的 WGS84 几何转换为高德使用的 GCJ-02，避免道路与底图错位。不要把含真实 Key 的 `.env` 提交到公开代码仓库。

海南高速出入口（`highway=motorway_junction`）会作为单独点图层显示，可在地图面板中开关，点击标记查看名称、编号和目的地。单独用已有拆分 GeoJSON 更新地图时，可先提取点图层，再传给地图脚本：

```bash
python3 scripts/extract_motorway_junctions.py \
  --input data/pbf/hainan-260922.osm.pbf \
  --output outputs/hainan/source/hainan_motorway_junctions.geojson
python3 scripts/visualize_guangdong_amap.py \
  --input-file outputs/hainan/split/links.geojson \
  --junction-file outputs/hainan/source/hainan_motorway_junctions.geojson \
  --output-file outputs/hainan/links_amap.html
```

要直接统计原始 PBF 中高速主线和匝道 Way 的 OSM 标签（含每个字段的覆盖数与常见值），运行：

```bash
python3 scripts/inspect_pbf_highways.py --input data/pbf/hainan-260922.osm.pbf --output outputs/hainan/pbf_highway_attributes.json
```

这项统计直接读取 PBF；`link_id`、`length_m`、`start_lng` 等处理脚本生成的字段不计入原始属性。

默认仅提取高速公路主体及高速匝道（`motorway`、`motorway_link`），输出到 `outputs/guangdong/`：

```text
guangdong_roads.geojson   # QGIS/网页地图
guangdong_roads.gpkg      # QGIS 推荐
guangdong_links.csv       # 带 link_id、起终点和长度
```

如需全部可驾驶道路：

```bash
python3 scripts/process_guangdong_pbf.py --all-drivable
```

如需额外加入主要干道或国省道，可以显式指定：

```bash
python3 scripts/process_guangdong_pbf.py --highway motorway motorway_link trunk trunk_link primary primary_link
```

OSM 几何为 WGS84（EPSG:4326），与原协议门架的 GCJ-02 不同，叠加分析前需要统一坐标系。

## 路链细粒度拆分

`scripts/split_links.py` 在已有路网的 GeoJSON 基础上拆分较长 Link，并在 `*_link`
（当前 OSM 数据中的匝道标识）接入主线的内部位置优先切割。它保留原始业务属性，
为子链写入 `source_link_id` 和从 1 开始的 `segment_index`，并输出原链到子链的映射。

拆分长度配置沿用本项目 `.env` / 环境变量方式：

```env
# 单条最终 Link 的最大长度，单位米；默认 1000
MAX_LINK_LENGTH=1000
# 可选：端点/匝道拓扑匹配容差和近零段阈值，单位米
LINK_SPLIT_SNAP_TOLERANCE_M=0.5
LINK_SPLIT_MIN_SEGMENT_LENGTH_M=1.0
```

例如处理当前 OSM 导出：

```bash
python3 scripts/split_links.py \
  --input hainan/guangdong_roads.geojson \
  --output-dir hainan/link_split \
  --max-link-length 1000
```

输出目录包括：

```text
links.geojson              # 已切分 Link（保留原属性，并更新长度、起终点）
link_relationships.json    # 重建关系；提供同源 PBF 时包含跨原链有向拓扑
link_mapping.json/.csv     # source_link_id 到所有子链 link_id 的映射
validation_report.json     # 长度、ID、连续性、守恒和关系引用校验
```

若有从基础 GIS 接口获得的关系原始 JSON，可显式传入，脚本会把入边改接到
首段、出边改接到末段，并加入相邻子链关系：

```bash
python3 scripts/split_links.py --input input.geojson --relationships link_relationship.json --output-dir link_split
```

默认再次处理已含 `source_link_id`、`segment_index` 的输出时会跳过它们，避免重复
拆分；需要按新阈值重新切分时加 `--resplit-existing`。可通过
`--rename-link-id OLD NEW` 安全更改一个输出 Link ID，已存在的 ID 会被拒绝且关系会同步更新。
输入优先使用现有的 GeoJSON；当前运行环境未安装 GeoPackage 读取依赖时，可使用与 GPKG
同批导出的 `.geojson` 文件。经纬度数据按与 OSM 导入相同的 EPSG:3857 米制口径计算；
已知输入已是米制投影坐标时可加 `--metric-mode planar`。

运行测试：

```bash
python3 -m unittest discover -v
```

## 使用 Kepler.gl 可视化

处理完成后可以运行：

```bash
python3 visualize_guangdong_kepler.py
```

然后用浏览器打开：

```text
outputs/guangdong/guangdong_roads_kepler.html
```

地图支持缩放、平移、道路属性悬浮查看。脚本会自动将图层转换为 WGS84，并只保留常用属性以控制 HTML 文件大小。

```bash
python3 scripts/fetch_gis_data.py
```

如果不使用 `.env`，也可以在当前终端中设置同名环境变量；环境变量优先于 `.env`。

也可指定版本、接口或输出目录：

```bash
python3 scripts/fetch_gis_data.py \
  --version 'V20260824114228' \
  --output-dir ./gis_data \
  --endpoint 'https://hainan-test.datasw.cn/bds/api/jsonrpc'
```

未指定 `--version` 时，脚本会先调用 `BDS_BASE_VERSION`，使用响应中的 `currentVersion`。调用失败会自动重试 2 次；可通过 `--timeout`、`--retries` 调整。

## 输出

每个版本隔离保存，避免覆盖历史数据：

```text
gis_data/
├── latest.json
└── V<版本号>/
    ├── raw/                 # JSON-RPC 原始响应，含 totalCount/result
    ├── csv/                 # UTF-8 with BOM，可直接由 Excel 打开
    ├── geojson/             # gantry、unit、link 图层
    └── validation_report.json
```

GeoJSON 中门架是 `Point`；收费单元、路链均以起终点构成临时 `LineString`。协议没有提供道路形状点，因此这些线不保证贴合实际道路中心线。

脚本会检查记录数、重复 ID、门架与路链、路链与收费单元、连通关系、方向和经纬度。发现问题时仍保留已下载文件，但以退出码 `1` 提醒调用方；确认要忽略可加 `--allow-validation-errors`。

## 坐标参考

协议明确说明门架坐标为 **GCJ-02**。收费单元和路链的坐标系在协议字段定义中没有明确标注，脚本因此把 GeoJSON 标为“需确认”，不会假定为 WGS84。与 GPS、OSM 或其他 WGS84 数据叠加前，请先向数据提供方确认并完成坐标转换。

## 安全说明

脚本不会打印请求头或密钥。避免把真实凭据放入 `README.md`、代码或版本控制；结束终端会话后可执行：

```bash
unset API_APP_ID API_APP_SECRET
```

## Vue 路链探索网页

已将当前海南路链演示整理为独立 Vue 3 网页，位于 `hainan-web/`。嵌入全部 10,680 条海南路链和 6,228 条拆分内部关系，支持地图搜索筛选、属性查看、前后段跳转、图层控制及 GeoJSON 导出。

```bash
npm --prefix hainan-web install
npm --prefix hainan-web run dev -- --port 5173
```

浏览器访问 `http://127.0.0.1:5173/`。默认复用项目 `.env` 中的高德 Web 端配置；地图服务不可用时仍可查看本地路网。更新 Python 流程输出后，运行 `npm --prefix hainan-web run data` 同步网页数据。构建、配置和数据口径见 `hainan-web/README.md`。
