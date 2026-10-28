# 实机校准指南 —— istSOS 消费侧只读桥 v0.1 校准与收紧

这是一份结果式校准指南，交给在真实 istSOS4 上执行校准的 AI Agent：
只描述要达成的结果、验收标准与红线，具体做法由执行者决定；但每一步
的原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

## 当前状态（2026-10-28，先说清已做到哪一步）

- ✅ 协议级自检已完成：`live/selftest.py` 对本地假 STA 服务端
  （回放固定 JSON）12/12 PASS。证明的是：MCP 握手与工具注册、
  参数超限以 LIMIT_EXCEEDED 拒绝、无/错 token 以 BAD_TOKEN 拒绝、
  未配置基地址以 NOT_CONFIGURED 如实回报、导出 GeoJSON 真实落盘、
  全程只发 GET。
- ⏭ 公开 STA demo 实测未做成：2026-10-28 对 FROST 公开 demo
  （frost.demo.52north.org、Fraunhofer IOSB airquality-frost）
  各尝试两次，本 VM 出网超时/空回，未连通，按口径跳过。
  **口径提醒：该项的对象是 FROST（另一种 STA 实现），即使将来
  连通并跑通，也只能记为“STA 协议级实测（对象为 FROST demo）”，
  绝不能写成 istSOS4 已验证。**
- ❌ istSOS4 本体未实测：本包与 istSOS4 的兼容性目前没有任何
  实测结论。以下才是 istSOS4 校准的正式流程。

## 目标结果（全部达成才算完成）

1. 一台真实 istSOS4（本地部署或用户指定的测试实例）上，
   `istsos_ping` 回报 server_reachable=true，landing entries
   与服务端实际提供的集合对得上。
2. `list_things` / `list_datastreams` 的结果与同一时刻直接用
   HTTP 请求该 istSOS4 STA 端点得到的原始 JSON 逐项一致
   （数量、id、名称、单位符号）。
3. 对一个已知内容的 Datastream，`get_observations` 返回的
   phenomenonTime / result 与原始 API 响应逐条一致；
   `export_observations_geojson` 生成的文件能在桌面 GIS
   （QGIS 等）打开，点位与该 Thing 在 istSOS4 里的 Location
   坐标一致，Feature 数与 limit 内观测数一致。
4. 负例全部成立：错 token → BAD_TOKEN；limit 超上限 →
   LIMIT_EXCEEDED；不存在的 datastream_id → 结构化错误
   （STA_HTTP_ERROR 或 STA_BAD_RESPONSE），不许假装成功、
   不许编造数据。
5. 校准结论回写：差异点（如 istSOS4 的 $expand 形状、nextLink
   行为、时间格式）逐条记录进本文件与包 README 的校准状态表，
   并重跑 `live/selftest.py` 保持全 PASS。

## 校准顺序（不要跳步）

1. **先 ping + discover**：完整回传两份 JSON 原文。ping 不通
   就停在这里，先解决部署/地址/网络，不许往下走。
2. **列表对账**：对同一端点分别用桥与 curl（或浏览器）取原始
   JSON，逐项核对 Things 与 Datastreams；差异逐条记录。
3. **观测对账**：选一个数据已知（或刚灌入已知测试值）的
   Datastream，桥取回的观测与原始响应逐条核对。
4. **导出验收**：导出 GeoJSON，在桌面 GIS 打开核对点位与
   Feature 数；同时核对导出文件 properties 里的
   geometry_note 口径是否与实际一致。
5. **负例验证**：按目标结果第 4 条逐项执行并留档。
6. **收紧与回归**：按实机差异改代码/文档口径（只许收紧，
   不许放宽硬上限来“适配”），跑 selftest，改动逐条回传。

## 红线（违反任意一条立即停下回报）

- **只读到底**：校准全程不许对 istSOS4 发任何写请求；
  需要测试数据时用 istSOS4 自带/官方示例数据或用户指定的
  测试实例，不许往生产实例灌数据。
- **不许把 FROST 或其他 STA 实现的实测说成 istSOS4 已验证**；
  也不许把假服务端自检说成真实服务端验证。
- **硬上限不许放宽**：实机遇到分页/条数对不上，先记录差异，
  不许改大 MAX_* 常量蒙混过关。
- 报错即留原文：任何一步失败，回传原始报错与响应，不许
  换地址、换实例反复试探到“看起来能跑”为止。
- 不许自行扩展工具集；发现 STA 形状与桥的假设不符，回报
  现场 JSON，等维护者据实收紧。
