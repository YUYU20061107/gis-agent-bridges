# Skill: postgis-consumer-bridge（PostGIS 消费侧只读桥）

让 AI Agent 通过固定查询模板消费 PostGIS 里的空间数据：看表的
几何列登记、属性列、行数与范围，把样本要素导出成 GeoJSON 文件。
数据与空间函数在数据库内的 PostGIS 里，本 Skill 只取结果。
本包不是 PostGIS 官方组件；本 Skill 只提供有限、受控的动作，
动作之外不许自行发挥。

## 版本基线

- PostgreSQL + PostGIS（目标库）、`psql` 客户端在 PATH、
  Python 3.x（桥只用标准库）。目标表须在 public schema。
- 本包**未实机校准**：当前只有协议自检级证据（见 README
  「状态声明」）。在真实环境完成 `docs/CALIBRATION.md` 之前，
  一切查库结果都按“模板已发出、语义待实机对账”口径回报，
  不许说成已验证可用。

## 运行前：token 与环境发现（每个新会话先做）

本包服务端**不会替调用方自动附带 `_token`**。每一次 tools/call
（包括 `postgis_ping` 与 `postgis_discover`）都必须在
`arguments` 里带 `_token`，否则 `BAD_TOKEN`。token 只按以下
来源取得，二者不要混用：

1. 若服务端进程设置了 `POSTGIS_BRIDGE_TOKEN`，使用该值；它
   优先于 token 文件；
2. 若未设置该环境变量，读取服务端 token 文件
   `~/.postgis-agent-bridge.token`（Windows：
   `%USERPROFILE%\.postgis-agent-bridge.token`）。两处都没有时，
   服务端会在启动时生成随机 token 并写入该文件。

真实 token 只用于调用，不许出现在回报、仓库文件或截图里。取得
token 后再做环境发现：

1. 先带 `_token` 调 `postgis_discover`：确认 psql 可用、
   SELECT 1 与 PostGIS 版本探针通过、`POSTGIS_ALLOWED_TABLES`
   已配置且包含本次要查的表。任何一项不通过，先停下回报，
   不许换着花样重试探活，更不许猜 token 反复试。
2. 明确本次要查的表与几何列来源（用户给定，或先经
   `postgis_list_spatial_tables` 看清 geometry_columns 登记），
   不许猜表名、猜列名。
3. 密码只经 `PGPASSWORD` 环境变量或 `~/.pgpass` 提供；不许把
   密码写进任何文件、参数或回报文本。

## 动作清单（v0.1，仅此这些；全部只读）

```
postgis_ping(_token=<token>)
postgis_discover(_token=<token>)
postgis_list_spatial_tables(_token=<token>)
postgis_table_columns(_token=<token>, table=<允许表>)
postgis_table_summary(_token=<token>, table=<允许表>, geom=<可选>)
postgis_export_geojson(_token=<token>, table=<允许表>, geom=<可选>,
                       limit=<1..1000 可选>, filename=<只给文件名 .geojson>,
                       output_dir=<可选>)
```

- `table_summary` 的 extent 为 null 就是空表，如实回报，不许
  编造范围；geom 有多个候选又没指定时桥会以 AMBIGUOUS_GEOM
  拒绝，先 list_spatial_tables 看清再指定。
- `export_geojson` 会覆盖同名文件；落盘后回报 path、bytes 与
  features 数，并用文件真实存在复核，不许只凭工具返回报成功。
  limit 超 1000 会被 LIMIT_EXCEEDED 拒绝，不要试图分批绕过
  上限把整表拖出来——那不是本桥的用途。
- 导出的 GeoJSON 若要进桌面 GIS，用本仓 qgis/ 包的
  `qgis_add_layer_from_path` 加载，并按 qgis 包自己的校准
  口径回报。
- 表不在允许集合、几何列不在登记里的报错原样回传，不许改查
  别的表/列绕过。

## 安全纪律（硬规则，违反即停）

1. **没有任意 SQL**：不许要求、也不许尝试让桥执行模板之外的
   查询；桥拒绝（BAD_TABLE_NAME / TABLE_NOT_ALLOWED /
   NOT_CONFIGURED / GEOM_NOT_FOUND）就是终局，回报用户决定，
   不许绕。
2. **只读到底**：v0.1 没有写库动作；任何“顺便更新一下表”的
   要求都不在本 Skill 范围内，停下回报。
3. **如实回报**：工具的 JSON 原文附在回报里；报错带
   error_code 与原始信息，不许把失败粉饰成成功，不许把协议
   自检说成实机校准。
4. **token 纪律**：`_token` 只从服务端 env 或 token 文件取
   （env 优先）；每次 tools/call 都要显式附带。不许把真实值
   写进回报或仓库文件，也不许在 `BAD_TOKEN` 后猜值重试。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `BAD_TOKEN` | 调用没带 `_token`，或值与服务端实际来源不一致 | 核对服务端是否设置了 `POSTGIS_BRIDGE_TOKEN`（它覆盖 token 文件）；否则读 token 文件；修正后重启服务端再调，不许猜值反复试 |
| `PSQL_NOT_AVAILABLE` | 本机没有 psql 或 POSTGIS_PSQL 指错 | 装 PostgreSQL 客户端或修正路径，停 |
| `NOT_CONFIGURED` | POSTGIS_ALLOWED_TABLES 未配置 | 让用户明确允许表集合后再查，停 |
| `TABLE_NOT_ALLOWED` / `BAD_TABLE_NAME` | 表不在允许集合 / 表名非法 | 回报用户，不许换表绕过 |
| `GEOM_NOT_FOUND` / `AMBIGUOUS_GEOM` | 几何列不在 geometry_columns 登记 / 多个几何列未指定 | 先 list_spatial_tables 看清登记，再显式指定 geom |
| `LIMIT_EXCEEDED` | 导出条数超 1000 硬上限 | 减小 limit；不许分批绕过 |
| `PSQL_FAILED` | 数据库侧报错（扩展未装、表不在 public、权限不足等） | 带原始报错回报，先核对扩展与 schema |
| `BAD_FILENAME` / `EXPORT_DIR_NOT_ALLOWED` | 导出文件名或落点违规 | 按规则改文件名/目录，不许穿越 |

## 回报格式

每次动作后回报：①一句话结论；②工具 JSON 原文；③涉及导出时，
列出落盘文件路径与复核结果；④若环境未过校准，注明“未实机
校准”口径。没有 JSON 的回报视为未执行。
