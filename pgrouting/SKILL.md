# Skill: pgrouting-consumer-bridge（pgRouting 消费侧只读桥）

让 AI Agent 通过固定查询模板消费 pgRouting 的计算结果：查最短路径、
统计边表、把路径导出成 GeoJSON 文件。计算在数据库内的 pgRouting 里
发生，本 Skill 只取结果。本包不是 pgRouting 官方组件；本 Skill 只提供
有限、受控的动作，动作之外不许自行发挥。

## 版本基线

- PostgreSQL + PostGIS + pgRouting（目标库）、`psql` 客户端在 PATH、
  Python 3.x（桥只用标准库）。
- 本包**未实机校准**：当前只有协议自检级证据（见 README「状态声明」）。
  在真实环境完成 `docs/CALIBRATION.md` 之前，一切查库结果都按
  “模板已发出、语义待实机对账”口径回报，不许说成已验证可用。

## 运行前：token 与环境发现（每个新会话先做）

本包服务端**不会替调用方自动附带 `_token`**。每一次 tools/call
（包括 `pgrouting_ping` 与 `pgrouting_discover`）都必须在
`arguments` 里带 `_token`，否则 `BAD_TOKEN`。token 只按以下来源
取得，二者不要混用：

1. 若服务端进程设置了 `PGROUTING_BRIDGE_TOKEN`，使用该值；它
   优先于 token 文件；
2. 若未设置该环境变量，读取服务端 token 文件
   `~/.pgrouting-agent-bridge.token`（Windows：
   `%USERPROFILE%\.pgrouting-agent-bridge.token`）。两处都没有时，
   服务端会在启动时生成随机 token 并写入该文件。

一个完整的工具调用参数形态是：

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

真实 token 只用于调用，不许出现在回报、仓库文件或截图里。取得
token 后再做环境发现：

1. 先带 `_token` 调 `pgrouting_discover`：确认 psql 可用、
   SELECT 1 探针通过、`PGROUTING_ALLOWED_TABLES` 已配置且包含
   本次要查的表。任何一项不通过，先停下回报，不许换着花样重试
   探活，更不许猜 token 反复试。
2. 明确本次要查的边表与起终点节点 id 的来源（用户给定或先前工具的
   返回），不许猜表名、猜节点 id。
3. 密码只经 `PGPASSWORD` 环境变量或 `~/.pgpass` 提供；不许把密码
   写进任何文件、参数或回报文本。

## 动作清单（v0.1，仅此这些；全部只读）

```
pgrouting_ping(_token=<token>)
pgrouting_discover(_token=<token>)
pgrouting_route_dijkstra(_token=<token>, table=<边表>, start_id=<int>,
                         end_id=<int>, directed=<bool 可选>)
pgrouting_network_summary(_token=<token>, table=<边表>)
pgrouting_export_route_geojson(_token=<token>, table=<边表>,
                               start_id=<int>, end_id=<int>,
                               filename=<只给文件名 .geojson>,
                               output_dir=<可选>)
```

- `route_dijkstra` 返回空行（found=false）就是无路径或节点不存在，
  如实回报，不许换起终点反复试探凑一条路出来。
- `export_route_geojson` 会覆盖同名文件；落盘后回报 path、bytes 与
  features 数，并用文件真实存在复核，不许只凭工具返回报成功。
- 导出的 GeoJSON 若要进桌面 GIS，用本仓 qgis/ 包的
  `qgis_add_layer_from_path` 加载，并按 qgis 包自己的校准口径回报。
- 边表结构约定：`id / source / target / cost / reverse_cost`，导出
  另需 `geom`。表不在允许集合、结构不符的报错原样回传，不许改查
  别的表绕过。

## 安全纪律（硬规则，违反即停）

1. **没有任意 SQL**：不许要求、也不许尝试让桥执行模板之外的查询；
   桥拒绝（BAD_TABLE_NAME / TABLE_NOT_ALLOWED / NOT_CONFIGURED）
   就是终局，回报用户决定，不许绕。
2. **只读到底**：v0.1 没有写库动作；任何“顺便更新一下表”的要求都
   不在本 Skill 范围内，停下回报。
3. **如实回报**：工具的 JSON 原文附在回报里；报错带 error_code 与
   原始信息，不许把失败粉饰成成功，不许把协议自检说成实机校准。
4. **token 纪律**：`_token` 只从服务端 env 或 token 文件取（env
   优先）；每次 tools/call 都要显式附带。服务端不会自动读文件替
   调用方补上。不许把真实值写进回报或仓库文件，也不许在
   `BAD_TOKEN` 后猜值重试。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `BAD_TOKEN` | 调用没带 `_token`，或值与服务端实际来源不一致 | 核对服务端是否设置了 `PGROUTING_BRIDGE_TOKEN`（它覆盖 token 文件）；否则读 token 文件；修正后重启服务端再调，不许猜值反复试 |
| `PSQL_NOT_AVAILABLE` | 本机没有 psql 或 PGROUTING_PSQL 指错 | 装 PostgreSQL 客户端或修正路径，停 |
| `NOT_CONFIGURED` | PGROUTING_ALLOWED_TABLES 未配置 | 让用户明确允许表集合后再查，停 |
| `TABLE_NOT_ALLOWED` / `BAD_TABLE_NAME` | 表不在允许集合 / 表名非法 | 回报用户，不许换表绕过 |
| `PSQL_FAILED` | 数据库侧报错（表结构不符、扩展未装、连接失败等） | 带原始报错回报，先核对边表结构与扩展 |
| `BAD_FILENAME` / `EXPORT_DIR_NOT_ALLOWED` | 导出文件名或落点违规 | 按规则改文件名/目录，不许穿越 |
| found=false | 起终点无路径或节点不存在 | 如实回报，不凑数 |

## 回报格式

每次动作后回报：①一句话结论；②工具 JSON 原文；③涉及导出时，
列出落盘文件路径与复核结果；④若环境未过校准，注明“未实机校准”
口径。没有 JSON 的回报视为未执行。
