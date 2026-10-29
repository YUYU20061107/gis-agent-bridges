# GeoServer 消费侧只读桥（gis-agent-bridges / geoserver）

> **English** — This package is a *consumer-side, read-only* bridge
> for GeoServer. It only reads your GeoServer's REST catalog
> (workspaces, layers, layer details) and OGC GetCapabilities
> summaries over HTTP GET — it creates, modifies and deletes
> nothing, and offers no arbitrary-URL fetching. Layer resource
> links returned by the server are treated as untrusted input and
> are only followed when they are same-origin with the configured
> base URL. **This is not an official GeoServer or OSGeo
> component.** Its current evidence level is protocol-level
> self-check only: it has **not yet been calibrated against a real
> GeoServer installation**.

让 AI Agent 在真正调用 WMS/WFS 之前，先把一个 GeoServer 里
“有什么”看清楚：有哪些工作区、哪些图层、某个图层的 CRS 与
范围是什么、GetCapabilities 里自报的标题与图层清单是什么。
本桥只做消费侧只读这一段——看目录、看摘要，不碰服务配置，
更不发布或删除任何图层。

## 定位声明（请先读这一段）

- **不是官方组件**：本包是 gis-agent-bridges 合集仓的社区
  小桥，不是 GeoServer 官方组件，与 GeoServer / OSGeo 官方
  项目无隶属关系。GeoServer 本体的文档、发行与支持请走其
  官方渠道。
- **只读到底**：对 GeoServer 只发 GET。没有任何创建/修改/
  删除图层、工作区、样式或数据的工具；也没有把观测或图层
  数据批量拖回本地的工具——要取数据请用你自己的 OGC 客户端
  按服务协议取，本桥只帮你先看清目录。
- **没有任意 URL 入口**：请求路径只由固定模板拼装（REST
  目录端点与 WMS/WFS GetCapabilities）。基地址只从环境变量
  读；工作区名、图层名先经字符集校验再 URL 编码。图层详情里
  服务端返回的 resource href 按不可信输入处理：只有与基地址
  同源才跟随，否则只回报、不断言。
- **诚实边界**：REST 列表端点没有服务端分页，桥在本地把
  返回截到 300 条并标注 `truncated=true`，不假装给全；
  GetCapabilities 只做摘要（标题＋名字清单），不回传整份
  XML，也不替你判断服务质量。

## 入口

### MCP 服务端（live/）

纯标准库 stdio MCP 服务端，6 个工具，自检脚本
`live/selftest.py`。启动方式、token 的读取来源、环境变量与
故障排查见 [`live/LIVE.md`](live/LIVE.md)。

| 工具 | 作用 | 风险 |
|---|---|---|
| geoserver_ping | 桥是否在线、基地址是否配置、/rest/about/version 可达与服务端版本 | 只读 |
| geoserver_discover | 环境发现：基地址、认证是否已配置（不报值）、硬上限、token 守卫与校准口径（校准用） | 只读 |
| geoserver_list_workspaces | 工作区名清单（REST /rest/workspaces.json，上限 300） | 只读 |
| geoserver_list_layers | 图层清单（name、type；可按工作区前缀过滤，上限 300） | 只读 |
| geoserver_layer_info | 单图层详情：类型、默认样式，并跟随同源 resource 取 CRS 与 bbox | 只读 |
| geoserver_capabilities_summary | WMS/WFS GetCapabilities 摘要：服务标题与图层/要素类型名 | 只读 |

### 命令行侧（scripts/）

| 文件 | 说明 |
|---|---|
| `scripts/geoserver_bridge.py` | HTTP/校验/解析库（服务端与探针共用，不单独执行） |
| `scripts/probe_api.py` | 校准探针：version、工作区/图层计数、WMS 标题，输出单行 JSON |

操作手册见 `SKILL.md`。

## 架构

```
AI Agent / MCP 客户端
      │  stdio（MCP 协议，_token 守卫常开）
      ▼
live/mcp_server.py（纯标准库，不监听任何网络端口）
      │  只拼固定路径模板；名字先过 geoserver_bridge.py 校验
      ▼
HTTP GET（可选 Basic 认证，密码只在请求头里）
      │
      ▼
你自己的 GeoServer（/rest 目录 + WMS/WFS GetCapabilities）
```

## 快速上手

### 先跑协议自检（无需 GeoServer）

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 12/12 PASS
```

自检在本机起一个假 GeoServer 服务端回放固定响应，只验证
MCP 协议、参数校验与 token 安全闸，不连接真实服务，也不是
实机校准。

### 接自己的 GeoServer

```bash
export GEOSERVER_BASE_URL=http://localhost:8080/geoserver
# 若 REST 目录需要认证：
export GEOSERVER_USER=<用户名> GEOSERVER_PASSWORD=<密码>
python3 scripts/probe_api.py
```

探针 `ready=true` 后，再把 `live/mcp_server.py` 注册进 MCP
客户端。若客户端负责拉起服务端，`GEOSERVER_BASE_URL`（与
认证变量）必须同样写进客户端配置的 `env` 段；只在另一个
终端 `export` 不会被 GUI 客户端自动继承。密码不要写进任何
仓库文件。

### token：首次调用先处理这一项

本包与桌面包不同：**服务端不会替调用方自动附带 `_token`**。
`tools/list` 可以列工具，但每一次 `tools/call`（包括
`geoserver_ping` 与 `geoserver_discover`）都必须在
`arguments` 里带 `_token`，否则返回 `BAD_TOKEN`。token
来源二选一：`GEOSERVER_BRIDGE_TOKEN` 环境变量（优先），或
token 文件 `~/.geoserver-agent-bridge.token`（首次启动两处
都没有时服务端生成随机 token 写入该文件，0600）。机制细节
与排查见 [`live/LIVE.md`](live/LIVE.md)。

## 安全模型

1. **GET-only**：唯一的网络出口只发 GET；工具面里没有任何
   写远端或写本地文件的动作。
2. **模板写死**：请求路径只有 REST 目录与 GetCapabilities
   两类固定模板，工具参数里没有、也不接受任何 URL 或路径
   片段。
3. **名字校验**：工作区名、图层名先过 `^[A-Za-z0-9_.-]+$`
   字符集校验（图层名至多一个冒号分隔工作区），再 URL
   编码进路径；非法名字在发请求前以 `BAD_NAME` 拒绝。
4. **href 同源守卫**：服务端返回的 resource href 按不可信
   输入处理，只有 scheme＋host＋port 与基地址一致才跟随，
   防止被恶意/被劫持的服务端当 SSRF 跳板。
5. **防拉爆硬上限**：单次响应 ≤ 2 MiB、超时 10 秒、列表
   ≤ 300 条（本地截断且如实标注 truncated）；超限响应以
   `RESPONSE_TOO_LARGE` 中止，不静默吞。
6. **密码纪律**：Basic 认证只从环境变量读，密码只出现在
   请求头里；日志（`~/.geoserver-agent-bridge/calls.jsonl`）
   只记工具名与成败，discover 只报“认证是否已配置”。
7. **token 守卫常开**：无 token 或错 token 的 tools/call
   一律 `BAD_TOKEN` 拒绝；服务端走 stdio，不监听网络端口。

## 状态声明

- **证据级别：协议自检（未实机校准）**。按本仓三级证据
  口径，本包目前只有协议自检级证据：开发机（VM，
  Python 3.12.3，2026-10-29）无 GeoServer 环境，
  `live/selftest.py` 在本机 127.0.0.1 起假 GeoServer 服务端
  回放固定 REST JSON 与 WMS XML，实跑结果 **12/12 PASS**
  （initialize、工具清单 6 个、ping/工作区/图层/图层详情/
  capabilities 正例、无 token 与错 token 拒绝、非法图层名
  在发请求前被拒、全程只发 GET、未配置基地址如实回报）。
- 同机 `scripts/probe_api.py` 在未配置基地址时实跑如实
  回报 `NOT_CONFIGURED`、退出码 1，未发出任何请求。
- **不要把自检通过当作已在真实 GeoServer 上验证**：REST
  目录 JSON 的版本差异（如 GeoServer 3.x 的字段变化）、
  认证与角色权限的实际行为、GetCapabilities 的命名空间
  差异，须按 `docs/CALIBRATION.md` 在真实 GeoServer 上
  逐项校准后才成立。

## 环境要求

- Python 3.x（服务端与脚本只用标准库，无第三方依赖，
  无 requirements）。
- 一个可达的 GeoServer（版本以实机校准为准）；REST 目录
  端点通常需要认证，桥只支持 Basic 认证（经环境变量）。

## 目录结构

```
geoserver/
├── README.md / SKILL.md / ROADMAP.md / ENGINEERING-PLAYBOOK.md
├── LICENSE / .gitignore
├── live/
│   ├── mcp_server.py        # stdio MCP 服务端（6 个只读工具，token 守卫常开）
│   ├── LIVE.md              # stdio 形态、token、启动、环境变量与故障排查
│   └── selftest.py          # 协议自检（本地假 GeoServer 服务端，12 项）
├── scripts/
│   ├── geoserver_bridge.py  # HTTP/校验/解析库
│   └── probe_api.py         # 实机校准探针（只读，GET）
├── docs/
│   └── CALIBRATION.md       # 实机校准工单（真实 GeoServer 环境）
└── examples/
    ├── mcp-client-config.json
    └── prompts.md
```

## 免责声明

本包按现状提供。目录结果取决于目标 GeoServer 的版本、配置
与权限；桥只保证“按固定模板如实取回并回传”，不保证目录
内容的业务正确性。GetCapabilities 摘要是服务端自报信息，
不构成对服务可用性的背书。

## License

MIT，见 `LICENSE`。
