# pgrouting 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP
  客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **占位符逐项替换，不要原样保留尖括号内容**：
  - `<ABSOLUTE_PATH_TO_PACKAGE>`：替换为 **gis-agent-bridges 仓库根
    目录**的绝对路径（即包含 `pgrouting/` 的那一层），因为后面已经
    拼了 `/pgrouting/live/mcp_server.py`；不要替换成 `pgrouting/`
    目录本身，否则会多出一层 `pgrouting/pgrouting`。
  - `<your_database>`：替换为目标 `PGDATABASE`；
    `<your_readonly_user>`：替换为目标只读 `PGUSER`；
    `<ABSOLUTE_EXPORT_DIR>`：替换为允许导出落盘的绝对目录。若不
    想固定导出根目录，可以删掉这一行，但 GUI 客户端的工作目录不
    确定，推荐保留并明确指定。
  - `PGROUTING_ALLOWED_TABLES` 的示例值是 `ways`；用包内 Docker
    样本时必须改成 `sample_ways`，同时把 `PGPORT` 改为 `54329`、
    `PGDATABASE` 改为 `pgrouting_sample`、`PGUSER` 改为
    `pgrouting`。样本用户是本地一次性环境的管理员，不是正式校准
    要求的只读用户。
- **`command` 跨平台替换**：示例写 `python`，适合多数 Windows
  Python 安装。macOS/Linux 若只有 `python3`，把 `command` 改为
  `python3`。Windows 若只有 Python Launcher，把 `command` 改为
  `py`，并在 `args` 数组最前面加一个 `"-3"` 元素。
- **token 配置不在 JSON 示例里是刻意的**：二选一——
  (1) 自己生成一个随机值，在客户端 `env` 里加
  `PGROUTING_BRIDGE_TOKEN` 并安全保存；或 (2) 不加这一项，让
  服务端首次启动时把随机 token 写到
  `~/.pgrouting-agent-bridge.token`（Windows：
  `%USERPROFILE%\.pgrouting-agent-bridge.token`），之后从该文件
  读取。无论哪种方式，服务端都**不会自动替调用方附带**：每次
  tools/call 的 `arguments` 里都要有同一个 `_token`，例如
  `{"_token":"<从 env 或 token 文件读到的值>", "table":"sample_ways", "start_id":1, "end_id":3}`（这是
  route 调用的参数内层，不是完整 JSON-RPC 外壳）。完整示例见
  `../live/LIVE.md`。真实 token 不要发到聊天、截图或仓库里。
- 密码不要写进配置文件：经启动客户端进程的 `PGPASSWORD` 环境变量
  或 `~/.pgpass` 提供。GUI 客户端不一定继承终端环境，样本试用可
  在 pgpass 中只为 `127.0.0.1:54329:pgrouting_sample:pgrouting`
  配置本地演示密码。
- 无常驻应用内桥（stdio 直连，本包不监听网络端口）：MCP 服务端用
  普通 Python 3 启动即可；token 守卫常开。
- 启动顺序：先配好 PG* 与 `PGROUTING_ALLOWED_TABLES`，跑一遍
  `live/selftest.py` 与 `scripts/probe_api.py` 留档，再注册服务端；
  注册或改 env 后要重启客户端拉起的服务端进程。

## 提示词示例（可直接对 Agent 说）

通用预期：Agent 应自行从已配置的 env 或 token 文件取得 `_token`
并在每次 tools/call 中附带，但不得在对话或回报里回显真实值。

### 样本烟雾试用（Docker 样本已启动、客户端已按上文改成 sample_ways 时）

> 用 pgrouting 桥对 sample_ways 做一次烟雾试用：先 discover，再查
> network_summary，然后查节点 1 到节点 3（directed=true）的路径。
> 把结果与 sample-network.sql 里预先手算的预期逐项对比：summary
> 应为 5 个节点、6 条边；路径节点应为 [1, 4, 5, 3]、边为
> [3, 4, 5]、total_cost 应为 3。对不上就停下并回传工具 JSON 原文，
> 不要改样本或改预期凑绿，也不要把烟雾试用说成正式实机校准。

### 环境发现

> 用 pgrouting_discover 看一下现在能连的库、允许查哪些表。

预期行为：只读回报；探针失败会如实给出 error_code，不粉饰。

### 查一条路径

> 用 pgrouting_route_dijkstra 查 ways 表里节点 1 到节点 3 的最短路径。

预期行为：只读；返回节点/边序列与 total_cost；无路径时 found=false
如实回报，不换起终点凑数。

### 导出给桌面 GIS

> 把刚才那条路径用 pgrouting_export_route_geojson 导出成
> route_1_3.geojson，再用 qgis 桥加载进 QGIS 看一下。

预期行为：先导出并复核文件落盘与 features 数，再按 qgis 包自己的
校准口径加载回报；两个包的证据级别分别认定，不互相背书。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义一致；
接入是否成功以工具真实返回为准，不要把协议自检通过当作已在真实
PostgreSQL+pgRouting 上校准——校准状态见包内 docs/CALIBRATION.md。
