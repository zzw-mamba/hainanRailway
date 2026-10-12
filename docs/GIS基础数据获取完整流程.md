# GIS 基础数据获取流程

> 基于《基础数据与感知数据通信协议 V1.0》整理  
> 适用场景：通过测试环境 JSON-RPC 接口获取门架、收费单元、路链及路链连通关系等基础 GIS / 路网数据。

---

## 1. 整体说明

该系统的数据获取分为两部分：

- **HTTP JSON-RPC 接口**：用于获取基础数据，包括门架、收费单元、路链、路链连通关系。
- **MQTT 接口**：用于接收实时感知数据，包括车型识别、车牌识别、ETC 感知数据。

因此：

```text
https://hainan-test.datasw.cn/bds/api/jsonrpc
```

用于获取基础 GIS / 路网数据。

而：

```text
210.12.11.164:51883
```

是 MQTT Broker，不是普通 HTTP / HTTPS Web 服务，不能直接通过浏览器访问。

整体关系如下：

```text
                     数据中台
                        │
              ┌─────────┴─────────┐
              │                   │
         HTTP JSON-RPC           MQTT
              │                   │
      基础 GIS / 路网数据      实时感知数据
              │                   │
          门架信息             车型识别
          收费单元             车牌识别
          Link 路链            ETC
          Link 连通关系
```

---

## 2. HTTP 接口基本信息

### 2.1 请求地址

```text
https://hainan-test.datasw.cn/bds/api/jsonrpc
```

### 2.2 请求方式

```text
POST
```

### 2.3 Content-Type

```text
application/json;charset=UTF-8
```

### 2.4 请求头

需要携带：

```text
api-app-id
api-app-secret
```

建议不要直接把密钥写死在命令历史中，可以先在终端中设置环境变量：

```bash
export API_APP_ID='填写协议中的 api-app-id'
export API_APP_SECRET='填写协议中的 api-app-secret'
```

检查是否设置成功：

```bash
echo $API_APP_ID
```

出于安全考虑，不建议在代码仓库、Markdown 文档或公开聊天中直接保存真实 `api-app-secret`。

---

## 3. JSON-RPC 请求格式

所有基础数据接口均采用 JSON-RPC 2.0。

标准请求格式：

```json
{
  "jsonrpc": "2.0",
  "method": "接口方法名",
  "params": {},
  "id": 1
}
```

标准响应格式：

```json
{
  "jsonrpc": "2.0",
  "result": {},
  "id": 1
}
```

发生错误时：

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32603,
    "message": "错误说明"
  },
  "id": 1
}
```

---

# 4. 获取 GIS 基础数据完整流程

推荐按照以下顺序：

```text
Step 1 获取当前基础数据版本
        ↓
Step 2 获取门架数据
        ↓
Step 3 获取收费单元数据
        ↓
Step 4 获取路链数据
        ↓
Step 5 获取路链连通关系
        ↓
Step 6 保存为 JSON / CSV / GeoJSON
        ↓
Step 7 导入 QGIS / 数据库
```

协议说明：每一次基础数据版本更新后，应同时下载：

```text
门架
收费单元
路链
路链连通性关系
```

---

# 5. Step 1：获取当前基础数据版本

## 5.1 方法名

```text
BDS_BASE_VERSION
```

## 5.2 请求参数

第一次请求时，没有本地版本，填写：

```json
{
  "version": "-1"
}
```

## 5.3 curl 示例

```bash
curl -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d '{
    "jsonrpc": "2.0",
    "method": "BDS_BASE_VERSION",
    "params": {
      "version": "-1"
    },
    "id": 1
  }'
```

## 5.4 当前测试环境实际返回

目前已成功获取：

```json
{
  "id": 1,
  "jsonrpc": "2.0",
  "result": {
    "currentNumber": 0,
    "currentVersion": "V20260824114228",
    "nextNumber": null,
    "nextUseTime": null,
    "nextVersion": null,
    "verUseTime": "2026-08-25T00:00:00"
  }
}
```

当前版本号：

```text
V20260824114228
```

后续接口都需要传这个版本号。

建议在终端中设置：

```bash
export GIS_VERSION='V20260824114228'
```

后续即可直接使用：

```bash
"$GIS_VERSION"
```

---

# 6. Step 2：获取门架信息

## 6.1 方法名

```text
BDS_GANTRY_LIST
```

## 6.2 请求参数

```json
{
  "version": "V20260824114228"
}
```

## 6.3 curl 示例

```bash
curl -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"method\": \"BDS_GANTRY_LIST\",
    \"params\": {
      \"version\": \"$GIS_VERSION\"
    },
    \"id\": 2
  }"
```

## 6.4 返回主要字段

```text
id              门架编号
version         基础数据版本
name            门架名称
linkId          门架所在路链
gantryType      门架类型
tollIntervals   收费单元编号
lat             纬度
lng             经度
stakeNum        桩号
gantryStatus    使用状态
startTime       起始日期
endTime         终止日期
gantryHex       门架 HEX
```

其中：

```text
lat / lng 使用 GCJ-02 坐标系
```

### GIS 作用

门架可以作为点图层：

```text
Point(lng, lat)
```

后续可通过：

```text
linkId
```

把门架挂接到对应 Link。

同时，实时 MQTT 数据中会出现：

```text
gantryHex
gantryName
gantryType
```

因此可以实现：

```text
实时车辆记录
   ↓
门架
   ↓
Link
   ↓
路网拓扑
```

---

# 7. Step 3：获取收费单元信息

## 7.1 方法名

```text
BDS_UNIT_LIST
```

## 7.2 curl 示例

```bash
curl -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"method\": \"BDS_UNIT_LIST\",
    \"params\": {
      \"version\": \"$GIS_VERSION\"
    },
    \"id\": 3
  }"
```

## 7.3 返回主要字段

```text
id              收费单元编号
version         基础数据版本
name            收费单元名称
length          收费里程，单位：米
startLat        起始计费位置纬度
startLng        起始计费位置经度
startStakeNum   起始计费位置桩号
endLat          终止计费位置纬度
endLng          终止计费位置经度
endStakeNum     终止计费位置桩号
endTime         停止收费时间
```

收费单元可以用于：

```text
Link 聚合
收费区间管理
路径收费分析
路网分层组织
```

---

# 8. Step 4：获取路链 Link 信息

这是 GIS 路网中最核心的数据。

## 8.1 方法名

```text
BDS_LINK_LIST
```

## 8.2 curl 示例

```bash
curl -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"method\": \"BDS_LINK_LIST\",
    \"params\": {
      \"version\": \"$GIS_VERSION\"
    },
    \"id\": 4
  }"
```

## 8.3 返回主要字段

```text
id              路链编号
version         基础数据版本
length          路链长度，单位：米
unitId          收费单元编号
startLat        起始位置纬度
startLng        起始位置经度
startStakeNum   起始位置桩号
endStakeNum     终止位置桩号
endLat          终止位置纬度
endLng          终止位置经度
```

## 8.4 GIS 表示方式

每条 Link 可以暂时表示成 LineString：

```json
{
  "type": "Feature",
  "properties": {
    "id": "LINK001",
    "length": 1000,
    "unitId": "UNIT001"
  },
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [startLng, startLat],
      [endLng, endLat]
    ]
  }
}
```

---

## 8.5 重要限制

当前协议提供的 Link 数据只有：

```text
起点坐标
终点坐标
```

没有看到：

```text
道路中间形状点
完整 polyline
geometry
WKT
GeoJSON coordinates
Shapefile
```

因此仅靠当前接口构建的道路几何，默认会表现为：

```text
起点 -------- 终点
```

而不是完全贴合真实高速公路弯曲形状。

如果项目需要真实道路中心线，需要进一步向图商或数据中台确认是否还可以提供：

```text
Shapefile
GeoJSON
WKT
Polyline
道路中心线 shape points
```

---

# 9. Step 5：获取 Link 连通关系

## 9.1 方法名

> 实际服务端方法已由用户确认并成功调用：`BDS_LINKREL_LIST`。下文保留协议原文旧拼写供对照，实际请求应使用 `BDS_LINKREL_LIST`。

协议中的方法名为：

```text
BDS_LINK_RRLATIONSHIP
```

注意协议原文就是：

```text
RRLATIONSHIP
```

不是标准英语拼写 `RELATIONSHIP`。

调用时建议严格按照协议使用：

```text
BDS_LINK_RRLATIONSHIP
```

## 9.2 curl 示例

```bash
curl -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"method\": \"BDS_LINK_RRLATIONSHIP\",
    \"params\": {
      \"version\": \"$GIS_VERSION\"
    },
    \"id\": 5
  }"
```

## 9.3 返回字段

```text
id              连通性关系编号
version         基础数据版本
currentLinkId   当前路链编号
nextLinkId      下一个路链编号
direction       行车方向
```

其中：

```text
direction = UP
direction = DOWN
```

出口路链没有下一跳时：

```text
nextLinkId = 0
```

---

## 9.4 拓扑关系示例

可以构造：

```text
LINK001 → LINK002
LINK002 → LINK003
LINK003 → LINK004
```

这些数据对于以下任务非常关键：

```text
车辆轨迹恢复
路径搜索
路径推演
地图匹配
ETC 轨迹拼接
视频车辆轨迹融合
异常路径识别
```

---

# 10. 推荐的本地数据表

建议至少保存以下 4 张基础表：

```text
gis_gantry
gis_unit
gis_link
gis_link_relationship
```

---

## 10.1 gis_gantry

```text
id
version
name
link_id
gantry_type
toll_intervals
lat
lng
stake_num
gantry_status
start_time
end_time
gantry_hex
```

---

## 10.2 gis_unit

```text
id
version
name
length
start_lat
start_lng
start_stake_num
end_lat
end_lng
end_stake_num
end_time
```

---

## 10.3 gis_link

```text
id
version
length
unit_id
start_lat
start_lng
start_stake_num
end_lat
end_lng
end_stake_num
```

---

## 10.4 gis_link_relationship

```text
id
version
current_link_id
next_link_id
direction
```

---

# 11. 建议保存原始 JSON

不要只保存转换后的 GIS 数据。

建议保留：

```text
raw/
├── base_version.json
├── gantry.json
├── unit.json
├── link.json
└── link_relationship.json
```

原因：

```text
1. 便于后续追溯原始数据
2. 便于重新转换
3. 便于接口异常排查
4. 便于做版本对比
5. 便于数据质量检查
```

---

# 12. 推荐输出目录

```text
gis_data/
│
├── raw/
│   ├── base_version.json
│   ├── gantry.json
│   ├── unit.json
│   ├── link.json
│   └── link_relationship.json
│
├── csv/
│   ├── gantry.csv
│   ├── unit.csv
│   ├── link.csv
│   └── link_relationship.csv
│
└── geojson/
    ├── gantry.geojson
    ├── unit.geojson
    └── link.geojson
```

---

# 13. GeoJSON 转换建议

## 13.1 门架

门架转为：

```text
Point
```

示例：

```json
{
  "type": "Feature",
  "properties": {
    "id": "G001",
    "name": "某门架"
  },
  "geometry": {
    "type": "Point",
    "coordinates": [
      110.123456,
      19.123456
    ]
  }
}
```

---

## 13.2 收费单元

若当前仅有起终点，可以暂时转为：

```text
LineString
```

```json
{
  "type": "LineString",
  "coordinates": [
    [startLng, startLat],
    [endLng, endLat]
  ]
}
```

---

## 13.3 Link

同样转为：

```text
LineString
```

```json
{
  "type": "LineString",
  "coordinates": [
    [startLng, startLat],
    [endLng, endLat]
  ]
}
```

---

# 14. 坐标系注意事项

协议明确写明门架坐标采用：

```text
GCJ-02
```

因此不要直接把它当成标准 WGS84。

如果：

```text
QGIS
PostGIS
GeoPandas
OSM
GPS
```

中的其他数据采用 WGS84，则需要统一坐标系后再融合。

推荐在数据表中明确保留：

```text
coordinate_system = GCJ-02
```

避免后续误用。

---

# 15. 一键测试四类数据

在已经设置：

```bash
export API_APP_ID='...'
export API_APP_SECRET='...'
export GIS_VERSION='V20260824114228'
```

之后，可以分别调用。

---

## 15.1 门架

```bash
curl -s -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"BDS_GANTRY_LIST\",
    \"params\":{\"version\":\"$GIS_VERSION\"},
    \"id\":2
  }"
```

---

## 15.2 收费单元

```bash
curl -s -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"BDS_UNIT_LIST\",
    \"params\":{\"version\":\"$GIS_VERSION\"},
    \"id\":3
  }"
```

---

## 15.3 Link

```bash
curl -s -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"BDS_LINK_LIST\",
    \"params\":{\"version\":\"$GIS_VERSION\"},
    \"id\":4
  }"
```

---

## 15.4 Link 连通关系

```bash
curl -s -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"BDS_LINK_RRLATIONSHIP\",
    \"params\":{\"version\":\"$GIS_VERSION\"},
    \"id\":5
  }"
```

---

# 16. 直接保存返回结果到文件

例如保存 Link：

```bash
curl -s -X POST 'https://hainan-test.datasw.cn/bds/api/jsonrpc' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -H "api-app-id: $API_APP_ID" \
  -H "api-app-secret: $API_APP_SECRET" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"BDS_LINK_LIST\",
    \"params\":{\"version\":\"$GIS_VERSION\"},
    \"id\":4
  }" > link.json
```

查看：

```bash
cat link.json
```

如果本机安装了 `jq`：

```bash
cat link.json | jq
```

安装：

```bash
brew install jq
```

---

# 17. 建议的正式数据获取流程

项目中建议不要每次手动 curl，而是实现自动化同步流程：

```text
程序启动
   ↓
调用 BDS_BASE_VERSION
   ↓
读取 currentVersion
   ↓
与本地 version 比较
   ↓
版本相同？
 ┌───────┴────────┐
 │                │
是               否
 │                │
跳过更新      下载四类基础数据
                  ↓
          数据完整性检查
                  ↓
          写入数据库 / 文件
                  ↓
          更新本地 version
```

---

# 18. 数据完整性检查建议

每次下载完后至少检查：

```text
1. result 是否为空
2. totalCount 是否与 result 数量一致
3. Link ID 是否唯一
4. 门架 ID 是否唯一
5. 门架 linkId 是否能在 Link 表中找到
6. Link unitId 是否能在 Unit 表中找到
7. currentLinkId 是否能在 Link 表找到
8. nextLinkId 是否为有效 Link 或 0
9. 经纬度是否为空
10. 经纬度是否落在合理范围
```

例如海南地区数据至少应避免：

```text
lat = 0
lng = 0
```

之类明显异常值。

---

# 19. GIS 数据与 MQTT 实时数据关联方式

基础数据与实时数据可以通过门架建立关联。

MQTT 实时感知数据中会包含：

```text
gantryHex
gantryName
gantryType
deviceId
```

基础门架表中包含：

```text
gantryHex
id
linkId
lat
lng
```

因此可以：

```text
MQTT 实时车辆数据
        │
        │ gantryHex
        ↓
   GIS 门架基础表
        │
        │ linkId
        ↓
      Link
        │
        │ nextLinkId
        ↓
   路网拓扑关系
```

进一步可用于：

```text
车辆轨迹拼接
多源车辆匹配
ETC 与视频融合
车辆运行路径恢复
交通状态统计
路径异常分析
```

---

# 20. MQTT 地址为什么浏览器打不开

MQTT 测试地址：

```text
210.12.11.164:51883
```

之前测试：

```bash
nc -vz 210.12.11.164 51883
```

结果：

```text
Connection succeeded
```

说明 TCP 端口是通的。

但是：

```bash
curl http://210.12.11.164:51883
```

返回：

```text
Empty reply from server
```

而：

```bash
curl -vk https://210.12.11.164:51883
```

返回 TLS 握手错误。

这是正常现象，因为：

```text
51883 = MQTT Broker
```

而不是：

```text
HTTP Server
```

因此需要 MQTT 客户端访问，例如：

```text
MQTTX
mosquitto_sub
Python paho-mqtt
```

不能直接使用浏览器打开。

---

# 21. 最终建议的数据层级

后续项目可以按以下方式组织：

```text
全国路网
   ↓
区域路网
   ↓
路段
   ↓
收费单元 / Link Set
   ↓
Link
   ↓
门架
   ↓
实时车辆感知数据
```

基础数据层：

```text
Unit
Link
Link Relationship
Gantry
```

实时数据层：

```text
VehicleType
Plate
ETC
```

通过：

```text
gantryHex
linkId
unitId
currentLinkId / nextLinkId
```

完成关联。

---

# 22. 当前已确认信息

目前已经成功确认：

```text
JSON-RPC 接口可访问
HTTPS 正常
鉴权正常
BDS_BASE_VERSION 可正常调用
```

当前基础数据版本：

```text
V20260824114228
```

启用时间：

```text
2026-08-25T00:00:00
```

下一步建议依次调用：

```text
BDS_GANTRY_LIST
BDS_UNIT_LIST
BDS_LINK_LIST
BDS_LINK_RRLATIONSHIP
```

并检查每个接口返回的：

```text
totalCount
result
```

如果能够正常返回数据，再进一步编写自动下载和 GeoJSON 转换脚本。
