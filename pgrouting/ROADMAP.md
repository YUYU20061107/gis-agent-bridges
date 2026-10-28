# ROADMAP —— pgRouting 消费侧只读桥演进与待校准清单

## 定位前提

pgRouting 的计算在数据库内，本包永远只做消费侧：固定模板取结果、
统计、导出文件。不做任意 SQL、不做写库、不实现路径算法、不进
pgRouting 主仓当组件。演进方向只有一个：在消费侧这条窄缝里把
模板覆盖与校准证据做扎实。

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | stdio MCP 服务端 5 个只读工具（ping / discover / route_dijkstra / export_route_geojson / network_summary）；scripts/pgrouting_bridge.py 固定三模板＋表名双重校验（标识符正则＋允许集合）＋参数强转；psql 子进程参数数组调用；token 守卫常开（无配置时生成随机 token 落文件 0600）；probe_api.py 只读探针；selftest 假 psql 替身协议自检 | VM 侧已验证（2026-10-28，Python 3.12.3）：py_compile 通过、selftest **12/12 PASS**、probe 如实回报无 psql；**未实机校准**（无 PostgreSQL+pgRouting 环境） |

## 待实机校准清单（按依赖顺序，工单全文见 docs/CALIBRATION.md）

1. **连通与版本**：真实 psql 连目标库，probe_api.py 全绿：PostGIS 与
   pgRouting 版本号落档，SELECT 1 与 summary 试算通过。
2. **路径模板对账**：对已知小图（如 osm2pgrouting 导入的样本 ways）
   手工核对一条路径的节点序列与总代价，与 QGIS/手算结果一致。
3. **GeoJSON 导出对账**：导出文件在 QGIS 里加载，几何与路径走向、
   features 计数（应为边数）与 route 返回逐项一致。
4. **负例验证**：无路径的起终点返回 found=false；删 geom 列的表
   导出时如实报 PSQL_FAILED；只读用户下五工具全通（证明不需要写
   权限）。
5. **收紧与回归**：按实机版本差异（pgr_dijkstra 返回列、json 聚合
   行为）修正模板或文档，跑 selftest 保持全 PASS，把校准结论回写
   README 状态声明。

## 候选后续（未立项，先过校准再谈）

- 模板扩充须逐条过同样的安全评审：候选如 pgr_drivingDistance 的
  固定模板、按边 id 集合导出子图；每加一条都要有对应的实机对账。
- 与 qgis/ 包的联动演示（路径 GeoJSON 经 QGIS 桥加载）排在 QGIS 包
  完成实机校准之后，演示结论按两包各自证据口径分别认定。
