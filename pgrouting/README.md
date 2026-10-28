# pgRouting 消费侧只读桥（gis-agent-bridges / pgrouting）

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

```bash
# 1) 准备连接与允许集合（密码只放环境变量或 ~/.pgpass，永不写入仓库文件）
export PGHOST=localhost PGPORT=5432 PGDATABASE=<库名> PGUSER=<只读用户>
export PGROUTING_ALLOWED_TABLES=ways          # 允许查询的边表，逗号分隔
export PGROUTING_EXPORT_DIR=<导出目录>        # 可选，设置后导出只能落在其中

# 2) 协议自检（无需 PostgreSQL，用假 psql 替身验证协议与安全闸）
python3 live/selftest.py

# 3) 实机探针（有真实环境时跑一次，输出留档）
python3 scripts/probe_api.py

# 4) 把 live/mcp_server.py 注册进你的 MCP 客户端（示例见 examples/）
```

token：首次启动若未配置 `PGROUTING_BRIDGE_TOKEN`、也无 token 文件，
服务端会生成随机 token 写入 `~/.pgrouting-agent-bridge.token`（0600），
每次 tools/call 须在参数里带 `_token`。

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
│   └── selftest.py       # 协议自检（假 psql 替身，12 项）
├── scripts/
│   ├── pgrouting_bridge.py  # 连接/校验/SQL 模板库
│   └── probe_api.py         # 实机校准探针（只读）
├── docs/
│   └── CALIBRATION.md    # 实机校准工单（PostgreSQL+pgRouting 环境）
└── examples/
    ├── mcp-client-config.json
    └── prompts.md
```

## 免责声明

本包按现状提供。查库结果取决于你数据库里的边表数据质量与 pgRouting
版本；桥只保证“按固定模板如实取回并回传”，不保证路径结果的业务
正确性。导出文件会覆盖同名文件，指定 filename 前请自行确认。

## License

MIT，见 `LICENSE`。
