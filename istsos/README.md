# istSOS 消费侧只读桥（gis-agent-bridges / istsos）

> **English** — This package is a *consumer-side, read-only* bridge: it lets
> an AI agent pull sensor data from any OGC SensorThings API (STA) server
> over plain HTTP GETs and export observations as GeoJSON files, so the data
> can flow into desktop GIS workflows (for example, loaded into QGIS through
> this collection's `qgis/` bridge). istSOS4 is the primary target server,
> but **this package is not part of istSOS and is not an official istSOS
> component** — it speaks the standard STA protocol from the client side
> only, and it offers no write tools at all. Calibration status is stated
> plainly below: protocol-level self-check only; **istSOS4 itself has not
> been tested yet**.

让 AI Agent 以 OGC SensorThings API 只读方式取传感器数据并导出 GeoJSON
的消费侧桥。对接对象是任意 STA 服务端（istSOS4 为首要目标）。

## 定位声明（请先读这一段）

- **消费侧，不是数据服务**：本桥负责把观测数据从 STA 服务端“带进”
  本地文件与桌面 GIS 工作流；它不提供数据服务、不托管传感器数据、
  不替代 istSOS 或任何 STA 服务端。
- **不是 istSOS 官方组件**：桥只按 STA 1.1 标准协议做客户端访问；
  能连 istSOS4 是因为 istSOS4 实现了 STA，不是因为本桥属于 istSOS。
- **全只读**：对远端只发 GET；没有任何创建/更新/删除实体的工具，
  也没有任意代码执行、任意 URL 抓取通道。唯一的本地写入是把观测
  导出成 GeoJSON 文件（文件名由桥生成，不接受外部指定文件名）。
- **能力如实标注**：见下方“校准状态”。协议自检通过 ≠ 真实服务端
  已验证；对其他 STA 实现（如 FROST）的实测也不等于 istSOS4 已验证。

## 工具（live/，stdio MCP，纯标准库）

| 工具 | 作用 | 风险 |
|---|---|---|
| istsos_ping | 桥是否在线、基地址是否配置、服务端根路径是否可达 | 只读 |
| istsos_discover | 环境发现：基地址、硬上限、token 守卫、导出目录、校准口径 | 只读 |
| istsos_list_things | 列 Things（id/名称/描述） | 只读 |
| istsos_list_datastreams | 列 Datastreams（id/名称/单位符号），可按 thing_id 过滤 | 只读 |
| istsos_get_observations | 取某个 Datastream 的观测（时间倒序，含 result） | 只读 |
| istsos_export_observations_geojson | 把观测导出为 GeoJSON 文件（几何=所属 Thing 的第一个 Location） | 只读远端·本地落文件 |

导出语义须知：STA 里观测本身不带几何，点位来自 Datastream 所属 Thing
的 Location，同一流的全部观测共用该点位——导出文件的
`properties.geometry_note` 会写明这一点；Thing 没有位置时返回
`NO_LOCATION` 并拒绝生成文件，不伪造坐标。

## 配置（环境变量）

| 变量 | 说明 |
|---|---|
| `ISTSOS_BASE_URL` | STA 服务端基地址（必填），形如 `http://localhost:8080/istsos4/v1.1`（占位示例，非真实服务），末尾不带 `/`；代码不写死任何真实地址 |
| `ISTSOS_BRIDGE_TOKEN` | tools/call 的 token（优先于 token 文件） |
| `ISTSOS_BRIDGE_TOKEN_FILE` | token 文件路径（可选，默认 `~/.istsos-agent-bridge.token`） |
| `ISTSOS_BRIDGE_OUTPUT_DIR` | 导出 GeoJSON 的默认输出目录（可选） |

token 守卫与本合集其他桥同口径：env 或 token 文件给出期望 token；
都没有时服务端启动生成随机 token 写入 token 文件；每次 tools/call
须带 `_token` 且一致，否则 `BAD_TOKEN` 拒绝。服务端走 stdio，
不监听网络端口。

## 防拉爆硬上限（代码常量，超限直接拒绝、不静默截断）

| 项 | 上限 |
|---|---|
| 单页 `$top` | 100 |
| 列表跟随 `@iot.nextLink` | 3 页、总量 300 条 |
| `get_observations` 条数 | 100 |
| 导出观测条数 | 500（每页 100、最多 5 页） |
| 单次响应读取 | 2 MiB |
| 请求超时 | 10 秒 |

## 快速开始

```
# 1) 协议级自检（不需要任何真实服务，自带本地假 STA 服务端）
python3 live/selftest.py

# 2) 配置真实/自建 STA 服务端后启动（示例地址为占位）
ISTSOS_BASE_URL=http://localhost:8080/istsos4/v1.1 python3 live/mcp_server.py
```

客户端接入示例见 `examples/`，操作手册见 `SKILL.md`，
使用说明见 `live/LIVE.md`。

## 校准状态（2026-10-28）

| 级别 | 状态 |
|---|---|
| 协议级自检（本地假 STA 服务端回放固定 JSON） | ✅ 已跑：`live/selftest.py` 12/12 PASS——工具注册、参数超限拒绝、无/错 token 拒绝、导出落盘与只读（全 GET）纪律均验过 |
| 公开 STA demo 实测 | ⏭ 已尝试未做成：对 FROST 公开 demo（frost.demo.52north.org、Fraunhofer IOSB airquality-frost）各试两次，本 VM 出网超时/空回，未连通，按口径跳过；**注意：即便连通，对象是 FROST 而非 istSOS，只能记为“STA 协议级实测（FROST demo）”** |
| istSOS4 本体实测 | ❌ 未实测——没有任何结论；按 `docs/CALIBRATION.md` 在真实 istSOS4 上完成对账后才许升级口径 |

## 架构

```
AI Agent ──stdio MCP──> live/mcp_server.py ──HTTP GET (urllib)──> 任意 STA 服务端
                              │                                    (istSOS4 等)
                              └── 导出 .geojson ──> 本地文件 ──> 桌面 GIS 工作流
```
