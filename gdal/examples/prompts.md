# gdal 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进
  你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae
  的 mcpServers 段）。
- **占位符逐项替换，不要原样保留尖括号内容**：
  - `<ABSOLUTE_PATH_TO_PACKAGE>`：替换为 **gis-agent-bridges
    仓库根目录**的绝对路径（即包含 `gdal/` 的那一层），
    因为后面已经拼了 `/gdal/live/mcp_server.py`；不要
    替换成 `gdal/` 目录本身，否则会多出一层 `gdal/gdal`。
  - 若 GDAL 四件工具不在客户端进程的 PATH 里，在 `env`
    里逐件加 `GDAL_BRIDGE_GDALINFO`、`GDAL_BRIDGE_OGRINFO`、
    `GDAL_BRIDGE_GDAL_TRANSLATE`、`GDAL_BRIDGE_OGR2OGR`
    指向各自完整路径。
- **`command` 跨平台替换**：示例写 `python`，适合多数
  Windows Python 安装。macOS/Linux 若只有 `python3`，把
  `command` 改为 `python3`。Windows 若只有 Python
  Launcher，把 `command` 改为 `py`，并在 `args` 数组最
  前面加一个 `"-3"` 元素。
- **token 配置不在 JSON 示例里是刻意的**：二选一——
  (1) 自己生成一个随机值，在客户端 `env` 里加
  `GDAL_BRIDGE_TOKEN` 并安全保存；或 (2) 不加这一项，让
  服务端首次启动时把随机 token 写到
  `~/.gdal-agent-bridge.token`（Windows：
  `%USERPROFILE%\.gdal-agent-bridge.token`），之后从该文件
  读取。无论哪种方式，服务端都**不会自动替调用方
  附带**：每次 tools/call 的 `arguments` 里都要有同一个
  `_token`，例如
  `{"_token":"<从 env 或 token 文件读到的值>", "path":"/data/dem.tif"}`。
  完整示例见 `../live/HEADLESS.md`。真实 token 不要发到
  聊天、截图或仓库里。
- 无常驻应用内桥（stdio 直连，本包不监听网络端口）：MCP
  服务端用普通 Python 3 启动即可；token 守卫常开。
- 启动顺序：先跑一遍 `live/selftest.py` 与
  `scripts/probe_api.py` 留档，再注册服务端；注册或改
  env 后要重启客户端拉起的服务端进程。

## 提示词示例（可直接对 Agent 说）

通用预期：Agent 应自行从已配置的 env 或 token 文件取得
`_token` 并在每次 tools/call 中附带，但不得在对话或回报
里回显真实值。转换类动作的 `confirm=true` 只能在本次
对话里得到用户明确同意后填入。

### 环境发现

> 用 gdal_discover 看一下四件 GDAL 工具的版本和可用格式。

预期行为：只读回报；工具缺失会如实给出 NOT_AVAILABLE，
不粉饰。

### 探查文件

> 用 gdal 桥看一下 /data/dem.tif 的驱动、尺寸和仿射变换，
> 再给一遍波段统计。

预期行为：只读；统计经 PAM 关闭计算，原件旁不会多出
.aux.xml。

### 格式转换（会触发 confirm 闸）

> 把 /data/roads.geojson 用 gdal_convert_vector 转成
> /data/roads.gpkg，格式 GPKG。

预期行为：Agent 先复述输入/输出/格式、等用户确认后才带
confirm=true 执行；落盘后用 gdal_vector_info 复核图层与
要素数再回报。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具
定义一致；接入是否成功以工具真实返回为准，不要把协议
自检通过当作已在真实 GDAL 上校准——校准状态见包内
docs/CALIBRATION.md。
