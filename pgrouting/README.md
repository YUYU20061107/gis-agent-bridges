# pgRouting 消费侧只读桥（gis-agent-bridges / pgrouting）

> **English** — This package is a *consumer-side, read-only* bridge for
> pgRouting. Routing is computed inside your own PostgreSQL database; the
> bridge only retrieves results through three fixed, parameterized SQL
> templates (a Dijkstra route, a network summary, and the same route as
> GeoJSON). It provides **no arbitrary-SQL tool and never writes to the
> database** — its only file write is a GeoJSON export explicitly
> requested by the caller. Table names must pass both an identifier
> check and an explicit allowlist. **This is not an official pgRouting,
> PostGIS, or OSGeo component.** Its current evidence level is
> protocol-level self-check only: it has **not yet been calibrated
> against a real PostgreSQL + PostGIS + pgRouting installation**.

让 AI Agent 通过**固定的参数化查询模板**调用 pgRouting 取路径结果：
查最短路径、看边表规模、把路径导出成 GeoJSON 文件。路径计算发生在
PostgreSQL 内的 pgRouting 里，本桥只做消费侧的一段——取结果、落文件，
供后续桌面 GIS（如本仓 `qgis/` 包）加载。

## 定位声明（请先读这一段）

- **不是官方组件**：本包是 gis-agent-bridges 合集仓的社区小桥，不是
  pgRouting 官方组件，与 pgRouting / PostGIS / OSGeo 官方项目无隶属
  关系。pgRouting 本体的文档、发行与支持请走其官方渠道。
- **位置在消费侧**：算在 pgRouting（数据库内），桥负责按模板取结果与
  落文件。桥不实现任何路径算法，不碰数据库里的数据——v0.1 五个工具
  全部只读，唯一的落盘动作是把查询结果写成调用方指定的新 GeoJSON
  文件。
- **没有任意 SQL 入口**：SQL 只有三条写死的模板（见 `scripts/
  pgrouting_bridge.py`）。边表名须过标识符正则＋允许集合双重校验；
  起终点 id、directed 在 Python 侧强转后才进入 psql 变量。想查模板
  之外的东西，请直接用你自己的数据库客户端，不要指望本桥放行。
- **诚实边界**：边表须是标准 pgRouting 边表结构（`id / source /
  target / cost / reverse_cost`，GeoJSON 导出另需 `geom` 列与
  PostGIS）。表结构不符时 psql 会如实报错，桥原样回传，不猜不凑。

## 入口

### MCP 服务端（live/）

纯标准库 stdio MCP 服务端，5 个工具，自检脚本 `live/selftest.py`。
启动方式、token 的读取来源、环境变量与故障排查见
[`live/LIVE.md`](live/LIVE.md)。

| 工具 | 作用 | 风险 |
|---|---|---|
| pgrouting_ping | 桥是否在线、psql 是否可用 | 只读 |
| pgrouting_discover | 环境发现：psql 可用性、连接环境状态（密码只报是否设置）、允许表集合、SELECT 1 探针（校准用） | 只读 |
| pgrouting_route_dijkstra | 固定 `pgr_dijkstra` 模板查一条最短路径（节点/边序列＋累计代价） | 只读 |
| pgrouting_export_route_geojson | 固定模板把一条路径经 `ST_AsGeoJSON` 导出为 GeoJSON 文件 | 只读查询＋写调用方指定的新文件 |
| pgrouting_network_summary | 边表只读统计：节点数（source/target 去重）/ 边数 | 只读 |

### 命令行侧（scripts/）

| 文件 | 说明 |
|---|---|
| `scripts/pgrouting_bridge.py` | 连接/校验/SQL 模板库（服务端与探针共用，不单独执行） |
| `scripts/probe_api.py` | 校准探针：psql 版本、SELECT 1、PostGIS/pgRouting 版本、允许表试算，输出单行 JSON |

操作手册见 `SKILL.md`。

## 架构

```
AI Agent / MCP 客户端
      │  stdio（MCP 协议，_token 守卫常开）
      ▼
live/mcp_server.py（纯标准库，不监听任何网络端口）
      │  只调三条固定模板；表名/参数先过 pgrouting_bridge.py 校验
      ▼
psql 子进程（参数数组，不经 shell；连接参数由 PG* 环境变量继承）
      │
      ▼
你自己的 PostgreSQL + PostGIS + pgRouting（计算发生在这里）
      │  路径结果
      ▼
GeoJSON 文件 ──►（可选）本仓 qgis/ 桥 qgis_add_layer_from_path 加载进 QGIS
```

## 快速上手

### 先跑协议自检（无需 PostgreSQL）

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 12/12 PASS
```

自检用假 psql 替身，只验证 MCP 协议、参数校验与 token 安全闸，
不连接数据库，也不是实机校准。

### 用自带样本从零试用（Docker）

`examples/docker-compose.yml` 给出 PostgreSQL 17 + PostGIS 3.5
+ pgRouting 3.7.3 的示例固定版本组合，端口只绑
`127.0.0.1:54329`；同目录的 `sample-network.sql` 会在数据卷
首次初始化时建好 `sample_ways`（5 个节点、6 条边）。本轮未实际
拉取或启动该镜像验证，首次启动需要联网拉取；若该固定标签在你
使用时不可拉取，应换成同一版本组合的可拉取标签并记录差异，不要
改用浮动的 `latest`。初始化脚本只在数据卷为空时执行，已经起过
旧样本时先在 `examples/` 里执行 `docker compose down -v` 删除
**仅该样本项目**的数据卷，再重新 `up`。

```bash
# 1) 在 pgrouting/ 目录起样本库，并等健康检查通过
cd examples
docker compose up -d --wait
docker compose ps
cd ..

# 2) 回到 pgrouting/ 后，设置连接与允许集合
#    下列演示密码只适用于这个可丢弃的本地样本库，不要复用。
export PGHOST=127.0.0.1
export PGPORT=54329
export PGDATABASE=pgrouting_sample
export PGUSER=pgrouting
export PGPASSWORD=pgrouting_local_only
export PGROUTING_ALLOWED_TABLES=sample_ways
# 可选：export PGROUTING_EXPORT_DIR=<导出目录>

# 3) 跑探针；ready 应为 true，summary_probe 应命中 sample_ways
python3 scripts/probe_api.py
```

探针之后，再把 `live/mcp_server.py` 注册进 MCP 客户端。若客户端
负责拉起服务端，上面第 2 步的非密码连接变量与
`PGROUTING_ALLOWED_TABLES` 必须同样写进客户端配置的 `env` 段；
只在另一个终端 `export` 不会被 GUI 客户端自动继承。密码不要
写进配置文件，按 `examples/prompts.md` 用 `~/.pgpass` 或客户端
自己的安全环境变量入口提供。跨平台命令与占位符替换也见该文件。

样本的预期值在运行桥之前已由 `sample-network.sql` 中的边表逐项
手算写明，参照不来自桥的输出：

- `pgrouting_network_summary(table="sample_ways")`：
  `node_count=5`、`edge_count=6`；
- `pgrouting_route_dijkstra(table="sample_ways", start_id=1,
  end_id=3, directed=true)`：节点序列 `[1, 4, 5, 3]`，边序列
  `[3, 4, 5]`，`total_cost=3`；
- 同一条路径导出 GeoJSON：应有 3 个 features。

这条路径是烟雾试用，不等于完成 `docs/CALIBRATION.md` 的正式校准：
它没有覆盖只读数据库用户、directed=false、无路径与缺 geom 等
全部验收项，本包的证据级别仍是未实机校准。

### 接自己的数据库

把连接变量换成你的库与只读用户，允许集合逐字列出要查的表，再跑
探针并注册服务端：

```bash
export PGHOST=<主机> PGPORT=<端口> PGDATABASE=<库名> PGUSER=<只读用户>
export PGROUTING_ALLOWED_TABLES=ways          # 允许查询的边表，逗号分隔
export PGROUTING_EXPORT_DIR=<导出目录>        # 可选，设置后导出只能落在其中
python3 scripts/probe_api.py
```

密码只放 `PGPASSWORD` 环境变量或 `~/.pgpass`，永不写入仓库文件。

### token：首次调用先处理这一项

本包与桌面包不同：**服务端不会替调用方自动附带 `_token`**。
`tools/list` 可以列工具，但每一次 `tools/call`（包括
`pgrouting_ping` 与 `pgrouting_discover`）都必须在 `arguments`
里带 `_token`，否则返回 `BAD_TOKEN`。

token 从哪里读，按服务端实际配置二选一：

1. 若给服务端进程设置了 `PGROUTING_BRIDGE_TOKEN`，就用这个值，
   它优先于 token 文件；
2. 若没设置该环境变量，就读
   `~/.pgrouting-agent-bridge.token`（Windows 为
   `%USERPROFILE%\.pgrouting-agent-bridge.token`）。首次启动若
   两处都没有，服务端会生成随机 token 并写入该文件（0600）。

带 `_token` 的完整调用形态如下（真实 token 不要写进仓库或回报）：

```json
{
  "name": "pgrouting_route_dijkstra",
  "arguments": {
    "_token": "<TOKEN_FROM_ENV_OR_TOKEN_FILE>",
    "table": "sample_ways",
    "start_id": 1,
    "end_id": 3,
    "directed": true
  }
}
```

机制细节与 `BAD_TOKEN` 排查见 [`live/LIVE.md`](live/LIVE.md)。

## 安全模型

1. **模板写死**：三条 SQL 模板在代码里固定，工具参数里没有、也不接受
   任何 SQL 片段。
2. **表名双重校验**：`^[A-Za-z0-9_]+$` 正则先行（字符集排除一切注入
   材料），再查 `PGROUTING_ALLOWED_TABLES` 允许集合；集合未配置时查库
   工具以 `NOT_CONFIGURED` 拒绝，不猜默认表。
3. **参数强转**：节点 id 强转 int、directed 强转 bool 后才以 psql 变量
   传入；调用方原文不拼进 SQL。
4. **子进程参数数组**：psql 以 argv 数组调用，不经 shell，不拼连接串。
5. **密码纪律**：连接参数只从 libpq 标准环境变量读；桥不读取、不记录
   `PGPASSWORD` 的值，日志（`~/.pgrouting-agent-bridge/runs.jsonl`）
   只记工具名、表名、状态与耗时。建议为桥配一个**只读数据库用户**。
6. **导出落点受控**：filename 只许文件名（禁路径分隔符、须 `.geojson`
   结尾）；设置了 `PGROUTING_EXPORT_DIR` 时，output_dir 必须落在其内。
7. **token 守卫常开**：无 token 或错 token 的 tools/call 一律
   `BAD_TOKEN` 拒绝；服务端走 stdio，不监听网络端口。

## 状态声明

- **证据级别：协议自检（未实机校准）**。按本仓三级证据口径，本包目前
  只有协议自检级证据：开发机（VM，Python 3.12.3，2026-10-28）无
  PostgreSQL+pgRouting 环境，`live/selftest.py` 用假 psql 替身回放
  罐装输出，实跑结果 **12/12 PASS**（initialize、工具清单 5 个、
  ping/discover、无 token 与错 token 拒绝、非法表名与表不在允许集合
  在查库前被拒、路径/统计正例解析、GeoJSON 落盘、导出路径穿越被拒）。
- 同机 `scripts/probe_api.py` 实跑如实回报 `psql_available: false`、
  退出码 1——psql 都没有，自然谈不上连通数据库。
- 本次补入英文摘要、`live/LIVE.md`、样本 SQL 与 Docker 起步环境，
  只降低试用门槛，**没有新增实机证据，也不改变上面的证据级别**；
  只有按 CALIBRATION 完成并回写结果后，才可调整校准状态。
- **不要把自检通过当作已在真实 pgRouting 上验证**：三条模板的真实
  语义（pgr_dijkstra 返回列、ST_AsGeoJSON 输出形态、目标版本差异）
  须按 `docs/CALIBRATION.md` 在真实 PostgreSQL+PostGIS+pgRouting 上
  逐项校准后才成立。

## 环境要求

- Python 3.x（服务端与脚本只用标准库，无第三方依赖，无 requirements）。
- PostgreSQL 客户端 `psql` 在 PATH 中（或用 `PGROUTING_PSQL` 指定）。
- 目标库：PostgreSQL + PostGIS + pgRouting（版本以实机校准为准）；
  建议只读用户；边表结构见定位声明。

## 目录结构

```
pgrouting/
├── README.md / SKILL.md / ROADMAP.md / ENGINEERING-PLAYBOOK.md
├── LICENSE / .gitignore
├── live/
│   ├── mcp_server.py     # stdio MCP 服务端（5 个只读工具，token 守卫常开）
│   ├── LIVE.md           # stdio 形态、token、启动、环境变量与故障排查
│   └── selftest.py       # 协议自检（假 psql 替身，12 项）
├── scripts/
│   ├── pgrouting_bridge.py  # 连接/校验/SQL 模板库
│   └── probe_api.py         # 实机校准探针（只读）
├── docs/
│   └── CALIBRATION.md    # 实机校准工单（PostgreSQL+pgRouting 环境）
└── examples/
    ├── mcp-client-config.json
    ├── prompts.md
    ├── docker-compose.yml  # PostgreSQL+PostGIS+pgRouting 样本环境
    └── sample-network.sql  # 5 节点/6 边样本图与独立手算预期
```

## 免责声明

本包按现状提供。查库结果取决于你数据库里的边表数据质量与 pgRouting
版本；桥只保证“按固定模板如实取回并回传”，不保证路径结果的业务
正确性。导出文件会覆盖同名文件，指定 filename 前请自行确认。

## License

MIT，见 `LICENSE`。
