# ROADMAP —— istsos 消费侧只读桥

## v0.1（当前，2026-10-28）

- stdio MCP 服务端（纯标准库）：ping / discover / list_things /
  list_datastreams / get_observations / export_observations_geojson，
  6 个工具全只读，对 STA 服务端只发 GET。
- token 守卫（env 或 token 文件，缺失时启动生成随机 token）、
  防拉爆硬上限（$top/分页/条数/响应大小/超时，超限拒绝不截断）。
- 协议级自检 `live/selftest.py`：本地假 STA 服务端回放，
  12/12 PASS。

## 下一步（按顺序，不跳步）

1. **istSOS4 本体校准**：按 `docs/CALIBRATION.md` 在真实 istSOS4
   上完成列表/观测对账、导出验收与负例验证，回写校准状态。
   这是本包当前最大的未完成项，其余功能排在它之后。
2. 公开 STA demo 协议级实测：在网络可达的环境里对公开 demo
   （如 FROST demo）跑一遍只读工具链，结论只记为
   “STA 协议级实测（对象注明）”，不升级 istSOS4 口径。
3. 视校准中发现的真实形状再决定是否收紧/增补（例如 istSOS4
   特定的分页或时间格式差异），不预先堆功能。

## 明确不做

- 任何写工具（创建/更新/删除 STA 实体）——消费侧定位不变。
- 数据服务/托管、订阅推送（STA MQTT 等）——那是服务端的事。
- 把本桥并入 istSOS 或任何 STA 服务端代码库——桥是仓外消费方，
  角色与维护面都不同。
