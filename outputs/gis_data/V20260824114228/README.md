# 海南基础 GIS 接口数据

通过项目 `scripts/fetch_gis_data.py` 从已配置的海南测试接口获取，使用根目录 `.env` 中的凭据。

- 版本：V20260824114228
- 门架：50 条
- 收费单元：58 条
- 路链：279 条
- 路链连通关系：275 条
- 门架与路链、路链与收费单元、连通关系引用、方向值及现有坐标校验通过。

`raw/` 保存 JSON-RPC 原始响应；`csv/` 保存可读表格；`geojson/` 保存门架点与收费单元、路链起终点连线；`validation_report.json` 保存校验结果。

门架坐标按协议为 GCJ-02，收费单元与路链坐标系待确认。接口 GeoJSON 的线几何仅连接起终点，不含道路中间形状点。此批接口数据与 `outputs/hainan/` 中的 OSM 路网分开保存。

用户确认服务端实际连通关系方法为 `BDS_LINKREL_LIST`，本次已成功获取 275 条关系；方向字段统计为 DOWN=141、UP=134。原始响应保存在 `raw/link_relationship.json`，表格保存在 `csv/link_relationship.csv`。

在项目根目录重新获取基础数据：

```bash
python3 scripts/fetch_gis_data.py --output-dir outputs/gis_data --with-link-relationship
```

不传 `--with-link-relationship` 时仅下载门架、收费单元和路链。
