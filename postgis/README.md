# PostGIS 消费侧只读桥（gis-agent-bridges / postgis）

> **English** — This package is a *consumer-side, read-only* bridge for
> PostGIS. Data and spatial functions live inside your own PostgreSQL;
> the bridge only retrieves table structure, row counts, extents and
> sample features through six fixed, parameterized SQL templates, and
> can export sample features as GeoJSON. It provides **no arbitrary-SQL
> tool and never writes to the database** — its only file write is a
> GeoJSON export explicitly requested by the caller. Table names must
> pass both an identifier check and an explicit allowlist; geometry
> column names must additionally be confirmed against
> `geometry_columns`. **This is not an official PostGIS or PostgreSQL
> component.** Its current evidence level is protocol-level self-check
> only: it has **not yet been calibrated against a real PostgreSQL +
> PostGIS installation**.

让 AI Agent 通过**固定的参数化查询模板**消费 PostGIS 里的空间
数据：看表里登记了哪些几何列、有哪些属性列、有多少行、范围多大，
或把样本要素导出成 GeoJSON 文件。数据与空间函数都在 PostgreSQL
内的 PostGIS 里，本桥只做消费侧的一段——取结构、取统计、落文件，
供后续桌面 GIS（如本仓 `qgis/` 包）加载。与同仓 pgrouting 包的
分工：pgrouting 管“路怎么走”，本包管“表里有什么”；两者共用同一
套 psql 子进程与安全口径。

## 定位声明（请先读这一段）

- **不是官方组件**：本包是 gis-agent-bridges 合集仓的社区小桥，
  不是 PostGIS / PostgreSQL 官方组件，与其官方项目无隶属关系。
  PostGIS 本体的文档、发行与支持请走其官方渠道。
- **位置在消费侧**：数据在你的库里，桥只按模板取结果与落文件。
  v0.1 六个工具全部只读，唯一的落盘动作是把查询结果写成调用方
  指定的新 GeoJSON 文件。
- **没有任意 SQL 入口**：SQL 只有六条写死的模板（见
  `scripts/postgis_bridge.py`）。表名须过标识符正则＋允许集合
  双重校验；几何列名须再经 `geometry_columns` 清单核对归属；
  条数上限等标量以 psql 变量传入。想查模板之外的东西，请直接用
  你自己的数据库客户端，不要指望本桥放行。
- **诚实边界**：目标表须位于 public schema；导出依赖
  `ST_AsGeoJSON` 与 `to_jsonb`。表结构不符时 psql 会如实报错，
  桥原样回传，不猜不凑。空表的 `ST_Extent` 是 NULL，桥回报
  extent=null 并注明，不编造范围。

## 入口

### MCP 服务端（live/）

纯标准库 stdio MCP 服务端，6 个工具，自检脚本 `live/selftest.py`。
启动方式、token 的读取来源、环境变量与故障排查见
[`live/LIVE.md`](live/LIVE.md)。

| 工具 | 作用 | 风险 |
|---|---|---|
| postgis_ping | 桥是否在线、psql 是否可用 | 只读 |
| postgis_discover | 环境发现：psql 可用性、连接环境状态（密码只报是否设置）、允许表集合、SELECT 1 与 PostGIS 版本探针（校准用） | 只读 |
| postgis_list_spatial_tables | 允许集合内各表在 geometry_columns 里登记的几何列（列名/类型/SRID） | 只读 |
| postgis_table_columns | 某允许表的属性列清单（information_schema 固定模板） | 只读 |
| postgis_table_summary | 某允许表的行数与几何范围（ST_Extent） | 只读 |
| postgis_export_geojson | 固定模板把某允许表前 N 个要素经 ST_AsGeoJSON 导出为 GeoJSON 文件（N 上限 1000） | 只读查询＋写调用方指定的新文件 |

### 命令行侧（scripts/）

| 文件 | 说明 |
|---|---|
| `scripts/postgis_bridge.py` | 连接/校验/SQL 模板库（服务端与探针共用，不单独执行） |
| `scripts/probe_api.py` | 校准探针：psql 版本、SELECT 1、PostGIS 版本、允许表几何列登记，输出单行 JSON |

操作手册见 `SKILL.md`。

## 架构

```
AI Agent / MCP 客户端
      │  stdio（MCP 协议，_token 守卫常开）
      ▼
live/mcp_server.py（纯标准库，不监听任何网络端口）
      │  只调固定模板；表名/几何列先过 postgis_bridge.py 校验
      ▼
psql 子进程（参数数组，不经 shell；连接参数由 PG* 环境变量继承）
      │
      ▼
你自己的 PostgreSQL + PostGIS（数据与空间函数在这里）
      │  结构 / 计数 / 范围 / 样本要素
      ▼
GeoJSON 文件 ──►（可选）本仓 qgis/ 桥 qgis_add_layer_from_path 加载进 QGIS
```

## 快速上手

### 先跑协议自检（无需 PostgreSQL）

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 13/13 PASS
```

自检用假 psql 替身，只验证 MCP 协议、参数校验与 token 安全闸，
不连接数据库，也不是实机校准。

### 接自己的数据库

```bash
export PGHOST=<主机> PGPORT=<端口> PGDATABASE=<库名> PGUSER=<只读用户>
export POSTGIS_ALLOWED_TABLES=parcels,buildings   # 允许查询的表，逗号分隔
export POSTGIS_EXPORT_DIR=<导出目录>              # 可选，设置后导出只能落在其中
python3 scripts/probe_api.py
```

探针 `ready=true` 后，再把 `live/mcp_server.py` 注册进 MCP
客户端。若客户端负责拉起服务端，非密码连接变量与
`POSTGIS_ALLOWED_TABLES` 必须同样写进客户端配置的 `env` 段；
只在另一个终端 `export` 不会被 GUI 客户端自动继承。密码只放
`PGPASSWORD` 环境变量或 `~/.pgpass`，永不写入仓库文件。

### token：首次调用先处理这一项

本包与桌面包不同：**服务端不会替调用方自动附带 `_token`**。
`tools/list` 可以列工具，但每一次 `tools/call`（包括
`postgis_ping` 与 `postgis_discover`）都必须在 `arguments`
里带 `_token`，否则返回 `BAD_TOKEN`。token 来源二选一：
`POSTGIS_BRIDGE_TOKEN` 环境变量（优先），或 token 文件
`~/.postgis-agent-bridge.token`（首次启动两处都没有时服务端
生成随机 token 写入该文件，0600）。机制细节与排查见
[`live/LIVE.md`](live/LIVE.md)。

## 安全模型

1. **模板写死**：六条 SQL 模板在代码里固定，工具参数里没有、
   也不接受任何 SQL 片段。
2. **表名双重校验**：`^[A-Za-z0-9_]+$` 正则先行（字符集排除一切
   注入材料），再查 `POSTGIS_ALLOWED_TABLES` 允许集合；集合未
   配置时查库工具以 `NOT_CONFIGURED` 拒绝，不猜默认表。
3. **几何列归属校验**：几何列名先经同样的字符集校验，再查该表
   在 `geometry_columns` 里的登记；不在登记里以 `GEOM_NOT_FOUND`
   拒绝。未显式传 geom 且该表几何列不唯一时以 `AMBIGUOUS_GEOM`
   拒绝，不猜。
4. **参数强转与变量绑定**：表名绑定（`:'tbl'`）与导出条数
   （`:lim`，Python 侧强转 int 且 1..1000）都以 psql 变量传入；
   调用方原文不拼进 SQL。
5. **子进程参数数组**：psql 以 argv 数组调用，不经 shell，不拼
   连接串。
6. **密码纪律**：连接参数只从 libpq 标准环境变量读；桥不读取、
   不记录 `PGPASSWORD` 的值，日志
   （`~/.postgis-agent-bridge/runs.jsonl`）只记工具名、表名、状态
   与耗时。建议为桥配一个**只读数据库用户**。
7. **导出上限与落点受控**：导出条数硬上限 1000，超限以
   `LIMIT_EXCEEDED` 拒绝而非静默截断；filename 只许文件名
   （禁路径分隔符、须 `.geojson` 结尾）；设置了
   `POSTGIS_EXPORT_DIR` 时，output_dir 必须落在其内。
8. **token 守卫常开**：无 token 或错 token 的 tools/call 一律
   `BAD_TOKEN` 拒绝；服务端走 stdio，不监听网络端口。

## 状态声明

- **证据级别：协议自检（未实机校准）**。按本仓三级证据口径，
  本包目前只有协议自检级证据：开发机（VM，Python 3.12.3，
  2026-10-29）无 PostgreSQL+PostGIS 环境，`live/selftest.py`
  用假 psql 替身回放罐装输出，实跑结果见下方与 ROADMAP 记录
  （initialize、工具清单 6 个、ping/discover、无 token 与错
  token 拒绝、非法表名与表不在允许集合在查库前被拒、几何列/
  属性列/计数与范围正例解析、GeoJSON 落盘、导出路径穿越被拒）。
- 同机 `scripts/probe_api.py` 实跑如实回报
  `psql_available: false`、退出码 1——psql 都没有，自然谈不上
  连通数据库。
- **不要把自检通过当作已在真实 PostGIS 上验证**：固定模板的
  真实语义（geometry_columns 视图口径、ST_Extent 空集行为、
  to_jsonb 属性形状、目标版本差异）须按 `docs/CALIBRATION.md`
  在真实 PostgreSQL+PostGIS 上逐项校准后才成立。

## 环境要求

- Python 3.x（服务端与脚本只用标准库，无第三方依赖，无 requirements）。
- PostgreSQL 客户端 `psql` 在 PATH 中（或用 `POSTGIS_PSQL` 指定）。
- 目标库：PostgreSQL + PostGIS（版本以实机校准为准）；建议只读
  用户；目标表须在 public schema。

## 目录结构

```
postgis/
├── README.md / SKILL.md / ROADMAP.md / ENGINEERING-PLAYBOOK.md
├── LICENSE / .gitignore
├── live/
│   ├── mcp_server.py     # stdio MCP 服务端（6 个只读工具，token 守卫常开）
│   ├── LIVE.md           # stdio 形态、token、启动、环境变量与故障排查
│   └── selftest.py       # 协议自检（假 psql 替身，13 项）
├── scripts/
│   ├── postgis_bridge.py # 连接/校验/SQL 模板库
│   └── probe_api.py      # 实机校准探针（只读）
├── docs/
│   └── CALIBRATION.md    # 实机校准工单（PostgreSQL+PostGIS 环境）
└── examples/
    ├── mcp-client-config.json
    └── prompts.md
```

## 免责声明

本包按现状提供。查库结果取决于你数据库里的数据质量与 PostGIS
版本；桥只保证“按固定模板如实取回并回传”，不保证结果的业务
正确性。导出文件会覆盖同名文件，指定 filename 前请自行确认。

## License

MIT，见 `LICENSE`。
