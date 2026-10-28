# istsos 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **必须替换**：args 里的 `<ABSOLUTE_PATH_TO_PACKAGE>` 换成本包在你机器上的绝对路径；env 里的 `ISTSOS_BASE_URL` 换成你的 STA 服务端基地址（文件里的 `http://localhost:8080/istsos4/v1.1` 只是占位示例，不是真实服务）；`ISTSOS_BRIDGE_TOKEN` 换成你自己的 token，或删掉这一行、改用服务端生成的 token 文件（默认 `~/.istsos-agent-bridge.token`）。
- 无常驻应用内桥、不占端口：本包是 stdio 消费侧只读桥，服务端只在客户端拉起时存在，对 STA 服务端只发 HTTP GET。

## 提示词示例（可直接对 Agent 说）

### 看服务端有什么

> 用 istsos_list_things 列出全部 Things，再用 istsos_list_datastreams 看每个 Thing 的数据流和单位。

预期行为：只读；若返回 `truncated=true`，说明还有更多没取完，Agent 会如实说明而不是当成全量。

### 取最近观测

> 用 istsos_get_observations 取 Datastream 1 最近 20 条观测。

预期行为：只读，按 phenomenonTime 倒序；limit 超过 100 会被 `LIMIT_EXCEEDED` 拒绝，不许改小数字绕过上限。

### 导出给桌面 GIS 用

> 用 istsos_export_observations_geojson 把 Datastream 1 的观测导出成 GeoJSON，我要加载进 QGIS 看。

预期行为：远端只读、本地落一个 `.geojson` 文件；几何是该 Thing 的站点点位（全流共用），不是逐条观测的位置；Thing 没有位置时返回 `NO_LOCATION`，不会编造坐标。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义一致；接入是否成功以工具真实返回为准，不要把协议自检通过当作已在真实 istSOS4 上校准——校准状态见包内 docs/CALIBRATION.md（当前：istSOS4 未实测）。
