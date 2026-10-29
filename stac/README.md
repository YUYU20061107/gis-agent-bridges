# STAC 消费侧只读桥（gis-agent-bridges / stac）

> **English** — This package is a *consumer-side, read-only*
> bridge for STAC (SpatioTemporal Asset Catalog) APIs. It only
> reads catalog metadata over HTTP GET: collection lists,
> collection extents and licenses, and item search results
> (returned as trimmed metadata, optionally exported as a
> GeoJSON footprint file). It never downloads the imagery
> assets themselves and offers no arbitrary-URL fetching.
> **This is not an official STAC or OGC component.** Its
> current evidence level is protocol-level self-check only:
> it has **not yet been calibrated against any real STAC
> catalog**.

让 AI Agent 在真正下载遥感影像之前，先把目录看清楚：这个
STAC 目录里有哪些集合、覆盖哪片区域与时段、许可是什么、
某个集合在指定范围内有哪些景、云量多少。检索命中的条目
可以导出成 GeoJSON 足印文件，进桌面 GIS 里与其它图层叠
着看，再决定下哪几景。本桥只做消费侧只读这一段——查目录、
落足印文件，不下影像本体。

## 定位声明（请先读这一段）

- **不是官方组件**：本包是 gis-agent-bridges 合集仓的社区
  小桥，不是 STAC / OGC 官方组件，与其官方项目无隶属
  关系。STAC 规范与各目录的文档请走其官方渠道。
- **只读到底**：对 STAC 服务端只发 GET（/search 用 GET
  形态，不用 POST）。没有任何写工具；不跟随条目资产
  （assets）链接下载数据——资产只回报键名清单，下载请用
  你自己的工具按集合许可进行（有些目录的资产需要签名
  URL，那是目录侧的机制，不在本桥范围内）。
- **没有任意 URL 入口**：请求路径只由固定模板拼装（落地
  页、/collections、/collections/<id>、/search）。基地址
  只从环境变量读；集合 id 先经字符集校验再 URL 编码；
  集合列表的 next 链接按不可信输入处理，只有与基地址
  同源才跟随。
- **诚实边界**：检索是元数据检索，不是数据分发。返回里的
  云量、平台等属性是目录自报值；条目足印几何原样取自
  目录响应。目录没给的属性就是没有，桥不推断、不补造。

## 入口

### MCP 服务端（live/）

纯标准库 stdio MCP 服务端，6 个工具，自检脚本
`live/selftest.py`。启动方式、token 的读取来源、环境变量
与故障排查见 [`live/LIVE.md`](live/LIVE.md)。

| 工具 | 作用 | 风险 |
|---|---|---|
| stac_ping | 桥是否在线、基地址是否配置、目录落地页可达（id/标题/conformsTo） | 只读 |
| stac_discover | 环境发现：基地址、API Key 是否已配置（不报值）、硬上限、token 守卫、导出目录与校准口径（校准用） | 只读 |
| stac_list_collections | 集合清单（id、标题、许可、时空范围、提供方；next 跟随上限 3 页/300 条） | 只读 |
| stac_get_collection | 单集合详情摘要（许可、时空范围、提供方、关键词） | 只读 |
| stac_search_items | 按集合（可加 bbox）检索条目元数据（id、时间、云量、平台、资产键名；上限 100） | 只读 |
| stac_export_items_geojson | 检索结果导出为 GeoJSON 足印文件（元数据属性，不含影像本体；上限 500） | 只读远端＋写调用方指定的新文件 |

### 命令行侧（scripts/）

| 文件 | 说明 |
|---|---|
| `scripts/stac_bridge.py` | HTTP/校验/整形库（服务端与探针共用，不单独执行） |
| `scripts/probe_api.py` | 校准探针：落地页、集合计数与首个集合 id，输出单行 JSON |

操作手册见 `SKILL.md`。

## 架构

```
AI Agent / MCP 客户端
      │  stdio（MCP 协议，_token 守卫常开）
      ▼
live/mcp_server.py（纯标准库，不监听任何网络端口）
      │  只拼固定路径模板；id/bbox 先过 stac_bridge.py 校验
      ▼
HTTP GET（可选 Bearer API Key，只在请求头里）
      │
      ▼
任意 STAC API 目录（公开目录或自建 stac-fastapi 等）
      │  条目元数据
      ▼
GeoJSON 足印文件 ──►（可选）本仓 qgis/ 桥加载进 QGIS 叠加查看
```

## 快速上手

### 先跑协议自检（无需任何 STAC 服务）

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 13/13 PASS
```

自检在本机起一个假 STAC 服务端回放固定响应，只验证 MCP
协议、参数校验与 token 安全闸，不连接真实目录，也不是
实机校准。

### 接一个真实目录

```bash
export STAC_BASE_URL=<STAC API 根地址>
# 若该目录需要 API Key：
export STAC_API_KEY=<你的 Key>
python3 scripts/probe_api.py
```

探针 `ready=true` 后，再把 `live/mcp_server.py` 注册进
MCP 客户端。若客户端负责拉起服务端，`STAC_BASE_URL`（与
Key）必须同样写进客户端配置的 `env` 段；只在另一个终端
`export` 不会被 GUI 客户端自动继承。Key 不要写进任何
仓库文件。

### token：首次调用先处理这一项

本包与桌面包不同：**服务端不会替调用方自动附带
`_token`**。`tools/list` 可以列工具，但每一次
`tools/call`（包括 `stac_ping` 与 `stac_discover`）都
必须在 `arguments` 里带 `_token`，否则返回 `BAD_TOKEN`。
token 来源二选一：`STAC_BRIDGE_TOKEN` 环境变量（优先），
或 token 文件 `~/.stac-agent-bridge.token`（首次启动两处
都没有时服务端生成随机 token 写入该文件，0600）。注意
桥 token 与目录的 API Key 是两回事，不要混用。机制细节
与排查见 [`live/LIVE.md`](live/LIVE.md)。

## 安全模型

1. **GET-only**：唯一的网络出口只发 GET；/search 也用 GET
   形态，不引入 POST。
2. **模板写死**：请求路径只有落地页、集合、集合详情与
   检索四类固定模板，工具参数里没有、也不接受任何 URL
   或查询字符串片段；检索只许 collections/limit/bbox
   三个参数。
3. **参数校验在发请求前**：集合 id 过 `^[A-Za-z0-9_.-]+$`
   字符集；bbox 四数经纬度范围与 min<max 在本地校验；
   limit 强转 int 且超硬上限以 `LIMIT_EXCEEDED` 拒绝，
   不静默截断。
4. **next 同源守卫**：集合列表的 next 链接按不可信输入
   处理，只有 scheme＋host＋port 与基地址一致才跟随，
   且页数与总量都有硬上限。
5. **防拉爆硬上限**：单次响应 ≤ 2 MiB、超时 10 秒、检索
   ≤ 100 条、导出 ≤ 500 条、列表 ≤ 3 页/300 条；超限
   响应以 `RESPONSE_TOO_LARGE` 中止。
6. **资产不下载**：条目只回报资产键名清单；桥不请求任何
   资产 href，避免被目录响应带着去抓任意地址。
7. **Key 与 token 纪律**：API Key 只从环境变量读、只出现
   在请求头；日志（`~/.stac-agent-bridge/calls.jsonl`）
   只记工具名与成败。桥 token 守卫常开，错 token 一律
   `BAD_TOKEN`；服务端走 stdio，不监听网络端口。

## 状态声明

- **证据级别：协议自检（未实机校准）**。按本仓三级证据
  口径，本包目前只有协议自检级证据：开发机（VM，
  Python 3.12.3，2026-10-29）未连任何真实 STAC 目录，
  `live/selftest.py` 在本机 127.0.0.1 起假 STAC 服务端
  回放固定 JSON，实跑结果 **13/13 PASS**（initialize、
  工具清单 6 个、ping/集合/详情/检索正例、limit 超限与
  非法 bbox 在发请求前被拒、无 token 与错 token 拒绝、
  导出 GeoJSON 落盘、全程只发 GET、未配置基地址如实
  回报）。
- 同机 `scripts/probe_api.py` 在未配置基地址时实跑如实
  回报 `NOT_CONFIGURED`、退出码 1，未发出任何请求。本仓
  所在 VM 的出网受限，公开目录（如 Planetary Computer）
  的连通性未在此环境验证，不要据此推断目录本身不可用。
- **不要把自检通过当作已在真实 STAC 目录上验证**：各
  目录实现差异（GET /search 的支持程度、next 链接形态、
  eo 扩展字段口径、资产签名机制）须按 `docs/CALIBRATION.md`
  在至少一个真实目录上逐项校准后才成立。

## 环境要求

- Python 3.x（服务端与脚本只用标准库，无第三方依赖，
  无 requirements）。
- 一个可达的 STAC API 目录（实现以实机校准为准）；部分
  目录需要 API Key（经环境变量以 Bearer 头发送）。

## 目录结构

```
stac/
├── README.md / SKILL.md / ROADMAP.md / ENGINEERING-PLAYBOOK.md
├── LICENSE / .gitignore
├── live/
│   ├── mcp_server.py     # stdio MCP 服务端（6 个只读工具，token 守卫常开）
│   ├── LIVE.md           # stdio 形态、token、启动、环境变量与故障排查
│   └── selftest.py       # 协议自检（本地假 STAC 服务端，13 项）
├── scripts/
│   ├── stac_bridge.py    # HTTP/校验/整形库
│   └── probe_api.py      # 实机校准探针（只读，GET）
├── docs/
│   └── CALIBRATION.md    # 实机校准工单（真实 STAC 目录）
└── examples/
    ├── mcp-client-config.json
    └── prompts.md
```

## 免责声明

本包按现状提供。目录内容由各 STAC 服务端维护，属性与足印
的正确性取决于目录方；桥只保证“按固定模板如实取回并回传”。
影像资产的下载与使用须遵守各集合的许可与目录方的服务
条款，本桥不参与、也不背书。

## License

MIT，见 `LICENSE`。
