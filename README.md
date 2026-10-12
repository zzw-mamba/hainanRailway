# 海南路链处理与可视化

项目包含 OSM 路网处理、路链拆分与校验，以及嵌入海南数据的 Vue 地图页面。以下命令均在项目根目录执行。

## 项目结构

```text
路链处理/
├── scripts/                # Python 数据下载、PBF 解析、路链拆分和 HTML 地图生成
├── data/pbf/               # 海南 OSM PBF；广东原始 PBF 因体积较大仅保存在本机
├── outputs/
│   ├── hainan/             # 海南处理结果：source/、split/、HTML 和属性统计
│   └── guangdong/          # 广东属性统计及后续处理结果
├── hainan-web/
│   ├── src/                # Vue 页面、地图组件和样式
│   ├── scripts/            # 网页数据打包和上下行推断
│   └── public/data/        # 网页读取的海南数据和方向报告
├── tests/                  # 路链、处理流程和方向标注测试
├── docs/                   # 处理说明、协议、方向依据及页面截图
├── .env                    # 本地配置与凭据
└── README.md
```

`data/` 保存原始输入，`outputs/` 保存处理结果，`hainan-web/public/data/` 保存网页生成数据。更新网页数据时重新运行 `data` 命令。

公开 Git 仓库不包含本机 `.env`、含高德安全密钥的旧版 `outputs/hainan/links_amap.html`、超过 GitHub 单文件限制的广东 PBF，以及本地协议 PDF。运行网页所需的海南数据已包含在仓库中；需要运行广东原始 PBF 处理时，须自行准备相应输入文件。

## 启动网页

```bash
npm --prefix hainan-web install
npm --prefix hainan-web run data
npm --prefix hainan-web run dev
```

访问 http://127.0.0.1:5173/ 。网页配置和操作说明见 [Vue 项目说明](hainan-web/README.md)。

## 处理路链

PBF 提取需要 `pyrosm geopandas pandas`，高德 HTML 生成需要在根目录 `.env` 中配置 `AMAP_KEY`。已有 GeoJSON 可直接进入拆分流程。

```bash
python3 scripts/run_link_pipeline.py \
  --input data/pbf/hainan-260922.osm.pbf \
  --output-dir outputs/hainan \
  --max-link-length 1000
```

网页左侧可直接设置最大长度并重新生成，生成完成后自动更新路网和关联。页面生成结果保存到 `outputs/hainan/generated/`。

完整参数和各脚本用法见 [处理流程说明](docs/processing.md)。环境变量中的相对路径按项目根目录配置；原有路径已同步迁移。

## 验证

```bash
python3 -m unittest discover -s tests -v
npm --prefix hainan-web run build
```

## 参考资料

- [GIS 基础数据获取流程](docs/GIS基础数据获取完整流程.md)
- [PBF 高速属性统计](docs/PBF高速属性统计.md)
- [OSM 跨原链拓扑](docs/osm_topology.md)
- [路链编号规则与追溯](docs/link_numbering.md)
- [接口数据与 OSM 关联说明](docs/association_notes.md)
- [上下行标注依据与局限](docs/direction_notes.md)
- 基础数据与感知数据通信协议：本地参考文件，未收录于公开仓库
