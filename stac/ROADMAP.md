# ROADMAP —— STAC 消费侧只读桥演进与待校准清单

## 定位前提

STAC 目录是各数据提供方的服务端，本包永远只做消费侧
只读：查集合、查条目元数据、导足印文件。不下载影像资产
本体、不做任意 URL 抓取、不做写操作、不进任何目录方
主仓当组件。演进方向只有一个：在只读检索这条窄缝里把
目录实现差异的对账证据做扎实。

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | stdio MCP 服务端 6 个只读工具（ping / discover / list_collections / get_collection / search_items / export_items_geojson）；scripts/stac_bridge.py 固定路径模板＋集合 id 字符集校验＋bbox 本地校验＋limit 硬上限拒绝＋next 同源守卫＋响应/超时硬上限；资产只报键名不下载；可选 Bearer API Key 只经环境变量；token 守卫常开（无配置时生成随机 token 落文件 0600）；probe_api.py 只读探针；selftest 本地假 STAC 服务端协议自检 | VM 侧已验证（2026-10-29，Python 3.12.3）：py_compile 通过、selftest **13/13 PASS**、probe 在未配置时如实回报 NOT_CONFIGURED；**未实机校准**（未连任何真实 STAC 目录） |

## 待实机校准清单（按依赖顺序，工单全文见 docs/CALIBRATION.md）

1. **连通与落地页**：一个真实目录上 probe_api.py 全绿，
   目录 id 与集合计数落档。
2. **集合对账**：集合清单与集合详情同原始 JSON 逐项
   一致。
3. **检索对账**：已知集合＋已知范围的条目数与首条属性
   与原始 /search 响应逐条一致；GET /search 的支持
   情况落档（只支持 POST 的目录如实记录为不支持）。
4. **导出对账**：足印 GeoJSON 在 QGIS 里加载，位置与
   计数对账通过。
5. **负例验证**：404/401 口径、LIMIT_EXCEEDED、
   BAD_TOKEN 全部成立。
6. **收紧与回归**：按实机差异（next 形态、eo 字段口径）
   修正解析或文档，跑 selftest 保持全 PASS，把校准
   结论回写 README 状态声明；第二个目录实现重复第
   3 步起的对账后再扩口径。

## 候选后续（未立项，先过校准再谈）

- 检索参数扩充须逐条过同样的安全评审：候选如 datetime
  时间范围（ISO 字符串形态与范围校验）、按云量上限过滤
  （数值强转后以 GET 参数传入）；每加一条都要有实机
  对账。
- 与 geoserver/istsos 等消费桥的目录对照（同区域的服务
  图层与 STAC 集合并列查看）排在各包分别完成实机校准
  之后，结论按各包证据口径分别认定。
- 资产下载永远不在候选内：那是数据分发，不是目录
  检索，定位不允许。
