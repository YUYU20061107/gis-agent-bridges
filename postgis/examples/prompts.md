# postgis 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的
  MCP 客户端配置（如 Claude Desktop / Cursor / Trae 的
  mcpServers 段）。
- **占位符逐项替换，不要原样保留尖括号内容**：
  - `<ABSOLUTE_PATH_TO_PACKAGE>`：替换为 **gis-agent-bridges
    仓库根目录**的绝对路径（即包含 `postgis/` 的那一层），因为
    后面已经拼了 `/postgis/live/mcp_server.py`；不要替换成
    `postgis/` 目录本身，否则会多出一层 `postgis/postgis`。
  - `<your_database>`：替换为目标 `PGDATABASE`；
    `<your_readonly_user>`：替换为目标只读 `PGUSER`；
    `<ABSOLUTE_EXPORT_DIR>`：替换为允许导出落盘的绝对目录。
    若不想固定导出根目录，可以删掉这一行，但 GUI 客户端的
    工作目录不确定，推荐保留并明确指定。
  - `POSTGIS_ALLOWED_TABLES` 的示例值是 `parcels`；接自己的库
    时改成真实允许表集合，逗号分隔、逐字写对。
- **`command` 跨平台替换**：示例写 `python`，适合多数 Windows
  Python 安装。macOS/Linux 若只有 `python3`，把 `command` 改为
  `python3`。Windows 若只有 Python Launcher，把 `command` 改为
  `py`，并在 `args` 数组最前面加一个 `"-3"` 元素。
- **token 配置不在 JSON 示例里是刻意的**：二选一——
  (1) 自己生成一个随机值，在客户端 `env` 里加
  `POSTGIS_BRIDGE_TOKEN` 并安全保存；或 (2) 不加这一项，让
  服务端首次启动时把随机 token 写到
  `~/.postgis-agent-bridge.token`（Windows：
  `%USERPROFILE%\.postgis-agent-bridge.token`），之后从该文件
  读取。无论哪种方式，服务端都**不会自动替调用方附带**：每次
  tools/call 的 `arguments` 里都要有同一个 `_token`，例如
  `{"_token":"<从 env 或 token 文件读到的值>", "table":"parcels"}`。
  完整示例见 `../live/LIVE.md`。真实 token 不要发到聊天、截图
  或仓库里。
- 密码不要写进配置文件：经启动客户端进程的 `PGPASSWORD` 环境
  变量或 `~/.pgpass` 提供。
- 无常驻应用内桥（stdio 直连，本包不监听网络端口）：MCP
  服务端用普通 Python 3 启动即可；token 守卫常开。
- 启动顺序：先配好 PG* 与 `POSTGIS_ALLOWED_TABLES`，跑一遍
  `live/selftest.py` 与 `scripts/probe_api.py` 留档，再注册
  服务端；注册或改 env 后要重启客户端拉起的服务端进程。

## 提示词示例（可直接对 Agent 说）

通用预期：Agent 应自行从已配置的 env 或 token 文件取得
`_token` 并在每次 tools/call 中附带，但不得在对话或回报里
回显真实值。

### 环境发现

> 用 postgis_discover 看一下现在能连的库、PostGIS 版本和允许
> 查哪些表。

预期行为：只读回报；探针失败会如实给出 error_code，不粉饰。

### 看一张表

> 用 postgis 桥看 parcels 表：先列它的几何列登记和属性列，
> 再给出行数和范围。

预期行为：只读；表不在允许集合时如实回报 TABLE_NOT_ALLOWED，
不换表绕过。

### 导出样本给桌面 GIS

> 把 parcels 表的前 100 个要素用 postgis_export_geojson 导出
> 成 parcels_sample.geojson，再用 qgis 桥加载进 QGIS 看一下。

预期行为：先导出并复核文件落盘与 features 数，再按 qgis 包
自己的校准口径加载回报；两个包的证据级别分别认定，不互相
背书。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义
一致；接入是否成功以工具真实返回为准，不要把协议自检通过
当作已在真实 PostgreSQL+PostGIS 上校准——校准状态见包内
docs/CALIBRATION.md。
