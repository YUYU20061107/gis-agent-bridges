# LIVE —— PostGIS 消费侧只读桥运行说明

## 形态

`live/mcp_server.py` 是纯 Python 标准库的 **stdio MCP 服务端**：

- 它没有常驻应用内桥，不监听任何 TCP 端口，也不提供 HTTP 服务。
- MCP 客户端按需拉起这个进程，双方只通过 stdin/stdout 传 MCP
  JSON-RPC；stdout 是协议通道，运行日志只写 stderr。
- 服务端唯一的外部连接，是按工具调用启动 `psql` 子进程，再由
  psql 按 `PG*` 环境变量连接你自己的 PostgreSQL。
- 六个工具全部不写数据库；唯一写文件动作是明确调用
  `postgis_export_geojson` 时生成调用方指定的新 GeoJSON。

首次使用前先看 `../README.md` 的定位与状态声明；接真实数据库后，
校准顺序与验收口径以 `../docs/CALIBRATION.md` 为准。手动直接运行
服务端时，它会静默等待 stdin 输入，这不是卡死——它在等 MCP 客户端
发 JSON-RPC 消息。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---:|---|
| `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` | 查库时 | libpq 标准连接参数，由 psql 读取 |
| `PGPASSWORD` 或 `~/.pgpass` | 视数据库认证而定 | 只供 psql 使用；桥不读取、不记录密码值 |
| `POSTGIS_ALLOWED_TABLES` | 查库时 | 允许查询的表，逗号分隔；未配置时查库工具以 `NOT_CONFIGURED` 拒绝 |
| `POSTGIS_BRIDGE_TOKEN` | 否 | 若设置，服务端以它为期望 token，优先于 token 文件 |
| `POSTGIS_EXPORT_DIR` | 否 | 设置后导出文件只能落在此目录内 |
| `POSTGIS_PSQL` | 否 | psql 不在 PATH 时指定其完整路径 |

注意进程归属：在终端里 `export` 的变量只对从该终端启动的服务端与
探针有效。若 Claude Desktop 等 GUI 客户端负责拉起服务端，必须把
同一组变量写进该客户端的 MCP 配置 `env` 段，不能指望它继承另一个
终端的 `export`。

## token 机制（调用方必须显式附带）

本包的 token 守卫常开：**服务端不会替调用方自动附带 `_token`**。
`initialize`、`tools/list` 与协议 `ping` 不查 token；每一次
`tools/call`（包括本包的 `postgis_ping` 与 `postgis_discover`）
都必须在 `arguments` 里亲自带上 `_token`，且与服务端期望值完全
一致，否则返回 `BAD_TOKEN`。

服务端按以下顺序确定期望 token：

1. 若服务端进程环境里有非空的 `POSTGIS_BRIDGE_TOKEN`，使用该值，
   不再看 token 文件；
2. 否则读取 token 文件：
   - Linux/macOS：`~/.postgis-agent-bridge.token`
   - Windows：`%USERPROFILE%\.postgis-agent-bridge.token`
3. 若环境变量未设、token 文件也不存在，服务端**启动时**生成一个
   随机 token，写入上述文件并尽量设为 0600，同时在 stderr 打印
   文件路径。

不要把真实 token 写进仓库、客户端配置示例、提示词、回报或截图；
也不要靠反复猜测重试 `BAD_TOKEN`。

### 完整 tools/call 示例

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "postgis_table_summary",
    "arguments": {
      "_token": "<TOKEN_FROM_ENV_OR_TOKEN_FILE>",
      "table": "parcels"
    }
  }
}
```

## 启动与注册

手动启动（通常只用于确认进程能起来，实际使用由 MCP 客户端拉起）：

```bash
python3 live/mcp_server.py
```

客户端注册示例见 `../examples/mcp-client-config.json`；占位符与跨
平台 `command` 的替换方式集中写在 `../examples/prompts.md`。

调用日志在 `~/.postgis-agent-bridge/runs.jsonl`，只记工具名、表名、
状态与耗时，不记密码和 token。

## 自检

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 13/13 PASS
```

自检用假 psql 替身验证协议、工具面与安全闸，不连接真实数据库。
自检通过仍只是协议自检级证据，不是实机校准。

## 故障排查

| 现象 | 先查什么 |
|---|---|
| `BAD_TOKEN` | 是否**每一次** tools/call 都带了 `_token`；值是否与服务端进程实际使用的来源一致。只要服务端 env 里设置了 `POSTGIS_BRIDGE_TOKEN`，它就覆盖 token 文件；改 env 或 token 后要重启服务端。 |
| 客户端列不出工具 | 先单独跑 `live/selftest.py`；再核对客户端配置中的 Python 命令与 `mcp_server.py` 绝对路径。手动启动后无输出是正常等待状态。 |
| `PSQL_NOT_AVAILABLE` | 在**拉起服务端的同一环境**里确认 `psql` 可用，或设置 `POSTGIS_PSQL` 为完整路径。GUI 客户端的 PATH 可能与终端不同。 |
| `NOT_CONFIGURED` | 给服务端进程设置 `POSTGIS_ALLOWED_TABLES`。只在另一个终端 export、但 GUI 客户端没继承时，仍会报这个错。 |
| `TABLE_NOT_ALLOWED` / `BAD_TABLE_NAME` | 表名必须只是 `[A-Za-z0-9_]+` 且逐字列入允许集合。 |
| `GEOM_NOT_FOUND` / `AMBIGUOUS_GEOM` | 该表在 geometry_columns 里的登记与预期不符：没有登记、或有多个几何列而调用未传 `geom`。先用 `postgis_list_spatial_tables` 看清登记再调。 |
| `PSQL_FAILED` | 数据库侧报错（PostGIS 未装、表不在 public schema、权限不足等）：带原始报错核对扩展与 schema，不要换表绕过。 |
| 改了配置却像没生效 | MCP 客户端通常缓存已拉起的服务端进程；修改 env、token 或允许表后，重启服务端或重启客户端再试。 |
