# ROADMAP —— PostGIS 消费侧只读桥演进与待校准清单

## 定位前提

PostGIS 的数据与空间函数在数据库内，本包永远只做消费侧：固定
模板取结构、统计与样本要素、导出文件。不做任意 SQL、不做写库、
不实现空间算法、不进 PostGIS 主仓当组件。与 pgrouting 包共用
psql 子进程形态与安全口径，分工是“表里有什么”（本包）对
“路怎么走”（pgrouting）。

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | stdio MCP 服务端 6 个只读工具（ping / discover / list_spatial_tables / table_columns / table_summary / export_geojson）；scripts/postgis_bridge.py 固定六模板＋表名双重校验（标识符正则＋允许集合）＋几何列归属校验＋参数强转/变量绑定；psql 子进程参数数组调用；导出条数硬上限 1000；token 守卫常开（无配置时生成随机 token 落文件 0600）；probe_api.py 只读探针；selftest 假 psql 替身协议自检 | VM 侧已验证（2026-10-29，Python 3.12.3）：py_compile 通过、selftest **13/13 PASS**、probe 如实回报无 psql；**未实机校准**（无 PostgreSQL+PostGIS 环境） |

## 待实机校准清单（按依赖顺序，工单全文见 docs/CALIBRATION.md）

1. **连通与版本**：真实 psql 连目标库，probe_api.py 全绿：
   PostGIS 版本号落档，SELECT 1 与允许表几何列登记对账通过。
2. **结构对账**：geometry_columns / information_schema 独立
   查询与桥的清单逐项一致。
3. **数值对账**：count(*) 与 ST_Extent 独立查询与 summary
   逐项一致；空表 extent=null 口径成立。
4. **导出对账**：导出文件在 QGIS 里加载，要素数、几何与属性
   与表内逐项一致。
5. **负例验证**：只读用户下六工具全通；GEOM_NOT_FOUND /
   AMBIGUOUS_GEOM / TABLE_NOT_ALLOWED 口径成立。
6. **收紧与回归**：按实机版本差异（geometry_columns 口径、
   to_jsonb 形状）修正模板或文档，跑 selftest 保持全 PASS，
   把校准结论回写 README 状态声明。

## 候选后续（未立项，先过校准再谈）

- 模板扩充须逐条过同样的安全评审：候选如按范围（bbox）过滤的
  样本导出（bbox 四值在 Python 侧强转 float 后以变量传入）、
  几何类型分布统计；每加一条都要有对应的实机对账。
- schema 限定：当前只认 public schema 的表；多 schema 支持
  须先设计 schema 名的同等双重校验，不许先放行再补。
- 与 qgis/ 包的联动演示（样本 GeoJSON 经 QGIS 桥加载）排在
  QGIS 包完成实机校准之后，演示结论按两包各自证据口径分别
  认定。
