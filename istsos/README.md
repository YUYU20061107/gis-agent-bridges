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

（以下命令以 `python3` 书写；Windows 上通常用 `python`，
`examples/` 的客户端配置同理——只有 `python3` 的 macOS/Linux
保持 `python3`。）

第 0 步：协议级自检（离线，不需要任何真实服务，自带本地假
STA 服务端回放固定 JSON）：

```
python3 live/selftest.py    # 期望最后一行 SELFTEST: 12/12 PASS
```

第 1 步（可选）：首次连通——先拿一个公开演示端点把链路探通：

```
ISTSOS_BASE_URL=https://ogc-demo.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1 python3 scripts/probe_api.py
# 期望：输出一行 JSON，root.ok 与 ready 为 true，things/datastreams 带计数
```

这个端点是 **Fraunhofer IOSB（德国弗劳恩霍夫 IOSB 研究所）
运营的 FROST-Server 公开演示实例**，写在其官方文档的
“public demo instance”处，基地址即上面的 `/v1.1`；只读的
欧洲空气质量服务 `https://airquality-frost.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1`
（同为 Fraunhofer IOSB 的 FROST 实例）也可作替代。

> ⚠️ **这台服务器是 FROST，不是 istSOS4。** 连通它只证明
> STA 协议级互通（落地页/计数/列表形状对得上），**不构成
> istSOS4 的任何验证结论**；校准口径仍按下表，istSOS4 本体
> 未实测。演示端点是公共共享环境，数据随时可能被他人改动，
> 只配做首次连通验证，不要拿里面的数据当结论依据。本机
> 网络到不了它时，跳过本步即可——第 0 步自检与第 2 步
> 自建服务端都不依赖它。

第 2 步：接你自己的 STA 服务端（自建 istSOS4 或其他实现）：

```
# 先用只读探针探一次并留档（不带任何默认端点，只发 GET）
ISTSOS_BASE_URL=http://localhost:8080/istsos4/v1.1 python3 scripts/probe_api.py

# 再由 MCP 客户端拉起服务端（地址换成你的，示例为占位）
ISTSOS_BASE_URL=http://localhost:8080/istsos4/v1.1 python3 live/mcp_server.py
```

### token：首次调用必读

- token 从哪来：环境变量 `ISTSOS_BRIDGE_TOKEN` 优先；没设时
  读 token 文件（默认 `~/.istsos-agent-bridge.token`）；两者
  都没有时，服务端**启动时生成一个随机 token 并写入该文件**。
- **每次 tools/call 都必须在 arguments 里带 `_token`**，与
  服务端这侧的 token 一致；缺失或错误一律回 `BAD_TOKEN`，
  桌面包那种“服务端自动读文件、调用方无感”的口径在本包
  不适用。
- 一个完整的 tools/call 示例（JSON-RPC，stdio 里一行一条）：

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "istsos_list_things", "arguments": {"_token": "<填 token 文件里那串，或你 env 里设的值>", "top": 5}}}
```

客户端接入示例见 `examples/`，操作手册见 `SKILL.md`，
使用说明见 `live/LIVE.md`。

## 校准状态（2026-10-28）

| 级别 | 状态 |
|---|---|
| 协议级自检（本地假 STA 服务端回放固定 JSON） | ✅ 已跑：`live/selftest.py` 12/12 PASS——工具注册、参数超限拒绝、无/错 token 拒绝、导出落盘与只读（全 GET）纪律均验过 |
| 公开 STA demo 实测 | ⏭ 已尝试未做成：对 FROST 公开 demo（frost.demo.52north.org、Fraunhofer IOSB airquality-frost）各试两次，本 VM 出网超时/空回，未连通，按口径跳过；「快速开始」第 1 步已给出经 Fraunhofer IOSB 官方文档核验的演示端点，供在网络可达的环境按 `scripts/probe_api.py` 复跑；**注意：即便连通，对象是 FROST 而非 istSOS，只能记为“STA 协议级实测（FROST demo）”** |
| istSOS4 本体实测 | ❌ 未实测——没有任何结论；按 `docs/CALIBRATION.md` 在真实 istSOS4 上完成对账后才许升级口径 |

## 架构

```
AI Agent ──stdio MCP──> live/mcp_server.py ──HTTP GET (urllib)──> 任意 STA 服务端
                              │                                    (istSOS4 等)
                              └── 导出 .geojson ──> 本地文件 ──> 桌面 GIS 工作流
```
