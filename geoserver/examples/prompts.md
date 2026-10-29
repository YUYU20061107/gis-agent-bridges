# geoserver 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进
  你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae
  的 mcpServers 段）。
- **占位符逐项替换，不要原样保留尖括号内容**：
  - `<ABSOLUTE_PATH_TO_PACKAGE>`：替换为 **gis-agent-bridges
    仓库根目录**的绝对路径（即包含 `geoserver/` 的那一层），
    因为后面已经拼了 `/geoserver/live/mcp_server.py`；不要
    替换成 `geoserver/` 目录本身，否则会多出一层
    `geoserver/geoserver`。
  - `GEOSERVER_BASE_URL` 的示例值是本机默认地址
    `http://localhost:8080/geoserver`；接自己的实例时改成
    真实地址（末尾不要带 `/`）。若 REST 目录需要认证，
    在 `env` 里再加 `GEOSERVER_USER` 与
    `GEOSERVER_PASSWORD` 两行——**密码写进客户端配置文件
    前先确认该文件的保管方式**，介意的话改为从启动客户端
    的进程环境提供。
- **`command` 跨平台替换**：示例写 `python`，适合多数
  Windows Python 安装。macOS/Linux 若只有 `python3`，把
  `command` 改为 `python3`。Windows 若只有 Python
  Launcher，把 `command` 改为 `py`，并在 `args` 数组最前面
  加一个 `"-3"` 元素。
- **token 配置不在 JSON 示例里是刻意的**：二选一——
  (1) 自己生成一个随机值，在客户端 `env` 里加
  `GEOSERVER_BRIDGE_TOKEN` 并安全保存；或 (2) 不加这一项，
  让服务端首次启动时把随机 token 写到
  `~/.geoserver-agent-bridge.token`（Windows：
  `%USERPROFILE%\.geoserver-agent-bridge.token`），之后从该
  文件读取。无论哪种方式，服务端都**不会自动替调用方
  附带**：每次 tools/call 的 `arguments` 里都要有同一个
  `_token`，例如
  `{"_token":"<从 env 或 token 文件读到的值>", "name":"topp:states"}`。
  完整示例见 `../live/LIVE.md`。真实 token 不要发到聊天、
  截图或仓库里。
- 无常驻应用内桥（stdio 直连，本包不监听网络端口）：MCP
  服务端用普通 Python 3 启动即可；token 守卫常开。
- 启动顺序：先配好 `GEOSERVER_BASE_URL`，跑一遍
  `live/selftest.py` 与 `scripts/probe_api.py` 留档，再注册
  服务端；注册或改 env 后要重启客户端拉起的服务端进程。

## 提示词示例（可直接对 Agent 说）

通用预期：Agent 应自行从已配置的 env 或 token 文件取得
`_token` 并在每次 tools/call 中附带，但不得在对话或回报里
回显真实值。

### 环境发现

> 用 geoserver_discover 和 geoserver_ping 看一下现在连的
> 是哪个 GeoServer、版本多少、目录能不能读。

预期行为：只读回报；探针失败会如实给出 error_code，不粉饰。

### 看目录

> 用 geoserver 桥列一下工作区，再列 topp 工作区的图层。

预期行为：只读；truncated=true 时如实说明目录被截断，
不说成全部。

### 看一个图层

> 用 geoserver_layer_info 看 topp:states 的 CRS 和范围，
> 再用 capabilities_summary 对一下 WMS 里有没有它。

预期行为：只读；REST 与 capabilities 口径不一致时以差异
形式回报，不替服务端圆场。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具
定义一致；接入是否成功以工具真实返回为准，不要把协议自检
通过当作已在真实 GeoServer 上校准——校准状态见包内
docs/CALIBRATION.md。
