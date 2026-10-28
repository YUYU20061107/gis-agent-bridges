# pgrouting 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP
  客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **必须替换**：args 里的 `<ABSOLUTE_PATH_TO_PACKAGE>` 换成本包在你
  机器上的绝对路径；env 里的库名、用户、导出目录换成你的真实值。
- 密码不要写进配置文件：经启动客户端进程的 `PGPASSWORD` 环境变量
  或 `~/.pgpass` 提供。
- 无常驻应用内桥（stdio 直连，本包不监听网络端口）：MCP 服务端用
  普通 Python 3 启动即可；token 守卫常开，服务端首次启动会把随机
  token 写到 `~/.pgrouting-agent-bridge.token`，tools/call 须带
  `_token`（由客户端/Agent 按桥的约定附带）。
- 启动顺序：先配好 PG* 与 `PGROUTING_ALLOWED_TABLES`，跑一遍
  `live/selftest.py` 与 `scripts/probe_api.py` 留档，再注册服务端。

## 提示词示例（可直接对 Agent 说）

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
