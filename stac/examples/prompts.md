# stac 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进
  你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae
  的 mcpServers 段）。
- **占位符逐项替换，不要原样保留尖括号内容**：
  - `<ABSOLUTE_PATH_TO_PACKAGE>`：替换为 **gis-agent-bridges
    仓库根目录**的绝对路径（即包含 `stac/` 的那一层），
    因为后面已经拼了 `/stac/live/mcp_server.py`；不要替换
    成 `stac/` 目录本身，否则会多出一层 `stac/stac`。
  - `STAC_BASE_URL` 的示例值 `https://example.org/stac`
    是占位地址，必须改成真实目录的 STAC API 根地址
    （末尾不要带 `/`）。若该目录需要 API Key，在 `env`
    里再加一行 `STAC_API_KEY`——**Key 写进客户端配置
    文件前先确认该文件的保管方式**，介意的话改为从启动
    客户端的进程环境提供。
- **`command` 跨平台替换**：示例写 `python`，适合多数
  Windows Python 安装。macOS/Linux 若只有 `python3`，把
  `command` 改为 `python3`。Windows 若只有 Python
  Launcher，把 `command` 改为 `py`，并在 `args` 数组
  最前面加一个 `"-3"` 元素。
- **token 配置不在 JSON 示例里是刻意的**：二选一——
  (1) 自己生成一个随机值，在客户端 `env` 里加
  `STAC_BRIDGE_TOKEN` 并安全保存；或 (2) 不加这一项，
  让服务端首次启动时把随机 token 写到
  `~/.stac-agent-bridge.token`（Windows：
  `%USERPROFILE%\.stac-agent-bridge.token`），之后从该文件
  读取。无论哪种方式，服务端都**不会自动替调用方附带**：
  每次 tools/call 的 `arguments` 里都要有同一个
  `_token`，例如
  `{"_token":"<从 env 或 token 文件读到的值>", "collection_id":"sentinel-2-l2a", "limit":10}`。
  完整示例见 `../live/LIVE.md`。真实 token 不要发到聊天、
  截图或仓库里。注意桥 token 与目录的 API Key 是两回事。
- 无常驻应用内桥（stdio 直连，本包不监听网络端口）：MCP
  服务端用普通 Python 3 启动即可；token 守卫常开。
- 启动顺序：先配好 `STAC_BASE_URL`，跑一遍
  `live/selftest.py` 与 `scripts/probe_api.py` 留档，再
  注册服务端；注册或改 env 后要重启客户端拉起的服务端
  进程。

## 提示词示例（可直接对 Agent 说）

通用预期：Agent 应自行从已配置的 env 或 token 文件取得
`_token` 并在每次 tools/call 中附带，但不得在对话或回报
里回显真实值。

### 环境发现

> 用 stac_discover 和 stac_ping 看一下现在连的是哪个
> STAC 目录、能不能达。

预期行为：只读回报；探针失败会如实给出 error_code，
不粉饰。

### 查集合与检索

> 用 stac 桥列一下集合，再看 sentinel-2-l2a 这个集合的
> 许可和时空范围，然后在 [113.0, 22.0, 114.0, 23.0] 范围
> 里检索最近的 10 条，回报每条的时间和云量。

预期行为：只读；云量注明是目录自报元数据；count 为 0
时如实回报，不放宽范围凑结果。

### 导出足印

> 把刚才检索到的条目用 stac_export_items_geojson 导出，
> 再用 qgis 桥加载进 QGIS 叠加底图看一下。

预期行为：先导出并复核文件落盘与 features 数，明确说明
导出的是足印与元数据、不是影像本体；再按 qgis 包自己的
校准口径加载回报，两个包的证据级别分别认定。

注：示例中的工具名与集合 id 均须按实际目录替换；接入是否
成功以工具真实返回为准，不要把协议自检通过当作已在真实
STAC 目录上校准——校准状态见包内 docs/CALIBRATION.md。
