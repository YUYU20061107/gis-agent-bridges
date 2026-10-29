# ROADMAP —— GeoServer 消费侧只读桥演进与待校准清单

## 定位前提

GeoServer 是服务端软件，本包永远只做消费侧只读：看 REST
目录与 OGC 能力摘要。不做任何写操作、不做数据批量下载、
不做任意 URL 抓取、不进 GeoServer 主仓当组件。演进方向只有
一个：在只读目录这条窄缝里把覆盖面与校准证据做扎实。

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | stdio MCP 服务端 6 个只读工具（ping / discover / list_workspaces / list_layers / layer_info / capabilities_summary）；scripts/geoserver_bridge.py 固定路径模板＋名字字符集校验＋href 同源守卫＋响应/列表/超时硬上限；Basic 认证只经环境变量；token 守卫常开（无配置时生成随机 token 落文件 0600）；probe_api.py 只读探针；selftest 本地假 GeoServer 服务端协议自检 | VM 侧已验证（2026-10-29，Python 3.12.3）：py_compile 通过、selftest **12/12 PASS**、probe 在未配置时如实回报 NOT_CONFIGURED；**未实机校准**（无 GeoServer 环境） |

## 待实机校准清单（按依赖顺序，工单全文见 docs/CALIBRATION.md）

1. **连通与版本**：真实 GeoServer 上 probe_api.py 全绿，
   版本号落档，目录计数与管理界面一致。
2. **目录对账**：工作区/图层清单与原始 REST JSON 逐项
   一致；大目录实例验证 truncated 标注。
3. **详情对账**：矢量与栅格各一个图层的 CRS 与范围与管理
   界面一致；href 形态（绝对/相对/跨源）差异落档。
4. **capabilities 对账**：WMS/WFS 摘要与原始 XML 逐项
   一致，包括图层组的命名出现方式。
5. **负例验证**：401/403 如实回报、404 结构化、BAD_NAME
   在发请求前拒绝。
6. **收紧与回归**：按实机差异（REST JSON 字段的版本变化、
   命名空间差异）修正解析或文档，跑 selftest 保持全 PASS，
   把校准结论回写 README 状态声明。

## 候选后续（未立项，先过校准再谈）

- 目录覆盖扩充须逐条过同样的安全评审：候选如样式清单
  （/rest/styles.json 只读）、数据存储清单（按工作区）；
  每加一条都要有对应的实机对账。
- WMS GetMap 小图预览不在候选内：那已经是数据获取，
  不属于“看目录”的定位，要取图请用 OGC 客户端。
- 与 istsos/stac 等消费桥的目录联动（如把图层清单与 STAC
  集合对照）排在各包分别完成实机校准之后，结论按各包证据
  口径分别认定。
