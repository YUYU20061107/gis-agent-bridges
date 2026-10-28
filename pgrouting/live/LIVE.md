# LIVE —— pgRouting 消费侧只读桥运行说明

## 形态

`live/mcp_server.py` 是纯 Python 标准库的 **stdio MCP 服务端**：

- 它没有常驻应用内桥，不监听任何 TCP 端口，也不提供 HTTP 服务。
- MCP 客户端按需拉起这个进程，双方只通过 stdin/stdout 传 MCP
  JSON-RPC；stdout 是协议通道，运行日志只写 stderr。
- 服务端唯一的外部连接，是按工具调用启动 `psql` 子进程，再由
  psql 按 `PG*` 环境变量连接你自己的 PostgreSQL。
- 五个工具全部不写数据库；唯一写文件动作是明确调用
  `pgrouting_export_route_geojson` 时生成调用方指定的新 GeoJSON。

首次使用前先看 `../README.md` 的定位与状态声明；接真实数据库后，
校准顺序与验收口径以 `../docs/CALIBRATION.md` 为准。手动直接运行
服务端时，它会静默等待 stdin 输入，这不是卡死——它在等 MCP 客户端
发 JSON-RPC 消息。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---:|---|
| `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` | 查库时 | libpq 标准连接参数，由 psql 读取；样本环境见下文 |
| `PGPASSWORD` 或 `~/.pgpass` | 视数据库认证而定 | 只供 psql 使用；桥不读取、不记录密码值 |
| `PGROUTING_ALLOWED_TABLES` | 查库时 | 允许查询的边表，逗号分隔；未配置时查库工具以 `NOT_CONFIGURED` 拒绝 |
| `PGROUTING_BRIDGE_TOKEN` | 否 | 若设置，服务端以它为期望 token，优先于 token 文件 |
| `PGROUTING_EXPORT_DIR` | 否 | 设置后导出文件只能落在此目录内 |
| `PGROUTING_PSQL` | 否 | psql 不在 PATH 时指定其完整路径 |

注意进程归属：在终端里 `export` 的变量只对从该终端启动的服务端与
探针有效。若 Claude Desktop 等 GUI 客户端负责拉起服务端，必须把
同一组变量写进该客户端的 MCP 配置 `env` 段，不能指望它继承另一个
终端的 `export`。

## token 机制（调用方必须显式附带）

本包的 token 守卫常开，且实现与桌面包不同：**服务端不会替调用方
自动附带 `_token`**。`initialize`、`tools/list` 与协议 `ping` 不查
token；每一次 `tools/call`（包括本包的 `pgrouting_ping` 与
`pgrouting_discover`）都必须在 `arguments` 里亲自带上 `_token`，
且与服务端期望值完全一致，否则返回 `BAD_TOKEN`。

服务端按以下顺序确定期望 token：

1. 若服务端进程环境里有非空的 `PGROUTING_BRIDGE_TOKEN`，使用该值，
   不再看 token 文件；
2. 否则读取 token 文件：
   - Linux/macOS：`~/.pgrouting-agent-bridge.token`
   - Windows：`%USERPROFILE%\.pgrouting-agent-bridge.token`
3. 若环境变量未设、token 文件也不存在，服务端**启动时**生成一个
   随机 token，写入上述文件并尽量设为 0600，同时在 stderr 打印
   文件路径。

因此，省略 `PGROUTING_BRIDGE_TOKEN` 时，典型顺序是：先让客户端
启动一次服务端（或手动启动它），再从 token 文件读出内容（去掉首尾
空白），之后每次调用都把这个值填进 `_token`。不要把真实 token
写进仓库、客户端配置示例、提示词、回报或截图；也不要靠反复猜测
重试 `BAD_TOKEN`。

PowerShell 读取示例（只把值放进当前会话变量，不回显）：

```powershell
$bridgeToken = (Get-Content "$env:USERPROFILE\.pgrouting-agent-bridge.token" -Raw).Trim()
```

POSIX shell 读取示例：

```bash
bridge_token="$(cat ~/.pgrouting-agent-bridge.token)"
```

### 完整 tools/call 示例

下面是原始 JSON-RPC 形态；`_token` 的值必须替换为你按上文从
环境配置或 token 文件取得的真实值。MCP 客户端/SDK 通常替你包好
JSON-RPC 外层，但 `arguments` 里仍要包含 `_token`：

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "pgrouting_route_dijkstra",
    "arguments": {
      "_token": "<TOKEN_FROM_ENV_OR_TOKEN_FILE>",
      "table": "sample_ways",
      "start_id": 1,
      "end_id": 3,
      "directed": true
    }
  }
}
```

同一会话里调用 `pgrouting_ping`、`pgrouting_discover`、
`pgrouting_network_summary` 或导出工具时也一样：工具参数之外，
每次都再带同一个 `_token`。

## 启动与注册

手动启动（通常只用于确认进程能起来，实际使用由 MCP 客户端拉起）：

```bash
python3 live/mcp_server.py
```

Windows 若使用 Python Launcher，可执行 `py -3 live\mcp_server.py`。
客户端注册示例见 `../examples/mcp-client-config.json`；占位符与跨
平台 `command` 的替换方式集中写在 `../examples/prompts.md`，不要
把占位符原样留在正式配置里。

调用日志在 `~/.pgrouting-agent-bridge/runs.jsonl`，只记工具名、表名、
状态与耗时，不记密码和 token。Windows 对应路径为
`%USERPROFILE%\.pgrouting-agent-bridge\runs.jsonl`。

## 自检

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 12/12 PASS
```

自检用假 psql 替身验证协议、工具面与安全闸，不连接真实数据库。
自检通过仍只是协议自检级证据，不是实机校准。

## 样本环境入口

`../examples/docker-compose.yml` 会在本机回环端口 54329 起一个
一次性的 PostgreSQL + PostGIS + pgRouting 样本库，并由
`../examples/sample-network.sql` 初始化 `sample_ways`。从零试用
的完整命令、环境变量与预期结果在 `../README.md`「快速上手」里；
该路径只做烟雾试用，正式校准仍按 `../docs/CALIBRATION.md` 执行。

## 故障排查

| 现象 | 先查什么 |
|---|---|
| `BAD_TOKEN` | 是否**每一次** tools/call 都带了 `_token`；值是否与服务端进程实际使用的来源一致。特别注意：只要服务端 env 里设置了 `PGROUTING_BRIDGE_TOKEN`，它就覆盖 token 文件；改 env 或 token 后要重启服务端。不要删 token 文件后在旧进程上继续试——重启后才会生成新文件。 |
| 客户端列不出工具 | 先单独跑 `live/selftest.py`；再核对客户端配置中的 Python 命令与 `mcp_server.py` 绝对路径。手动启动后无输出是正常等待状态，不要往它的 stdout 混入自写日志。 |
| `PSQL_NOT_AVAILABLE` | 在**拉起服务端的同一环境**里确认 `psql` 可用，或设置 `PGROUTING_PSQL` 为完整路径。GUI 客户端的 PATH 可能与终端不同。 |
| `NOT_CONFIGURED` | 给服务端进程设置 `PGROUTING_ALLOWED_TABLES`。只在另一个终端 export、但 GUI 客户端没继承时，仍会报这个错。 |
| `TABLE_NOT_ALLOWED` / `BAD_TABLE_NAME` | 表名必须只是 `[A-Za-z0-9_]+` 且逐字列入允许集合。样本表名是 `sample_ways`，不是 `ways`。 |
| `PSQL_FAILED` 且连接被拒绝 | 数据库是否已启动并健康；样本环境应连 `127.0.0.1:54329`，不是容器内部的 5432，也不要只写可能先解析到 IPv6 的 `localhost`。 |
| `PSQL_FAILED` 且扩展/函数不存在 | 目标库是否真的装有 PostGIS 与 pgRouting，并已对当前库执行 `CREATE EXTENSION`。样本 SQL 已包含两条可重复执行的创建语句。 |
| 样本表不存在或还是旧数据 | PostgreSQL 初始化 SQL 只在数据卷为空时执行。若样本卷已经初始化过，在 `examples/` 里执行 `docker compose down -v` 删除**仅该样本项目**的数据卷，再 `docker compose up -d`。执行前确认没有把真实数据放进这个样本库。 |
| 导出 `BAD_GEOJSON` | 边表是否有 `geom` 列且几何可由 PostGIS 输出；纯路径/统计不依赖 geom，但导出依赖。 |
| 改了配置却像没生效 | MCP 客户端通常缓存已拉起的服务端进程；修改 env、token 或允许表后，重启服务端或重启客户端再试。 |
