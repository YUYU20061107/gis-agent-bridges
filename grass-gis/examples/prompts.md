# grass-gis 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进
  你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae
  的 mcpServers 段）。
- **占位符逐项替换，不要原样保留尖括号内容**：
  - `<ABSOLUTE_PATH_TO_PACKAGE>`：替换为 **gis-agent-bridges
    仓库根目录**的绝对路径（即包含 `grass-gis/` 的那一层），
    因为后面已经拼了 `/grass-gis/live/mcp_server.py`；不要
    替换成 `grass-gis/` 目录本身，否则会多出一层
    `grass-gis/grass-gis`。
  - `<ABSOLUTE_PATH_TO_GRASS_DATABASE>`：替换为你的 GRASS
    数据库根目录（gisdbase）的绝对路径，即其下直接有
    location 目录的那一层。桥不会替你新建 gisdbase、
    location 或 mapset，先用 GRASS 自己建好。
  - 若 `grass` 不在客户端进程的 PATH 里，在 `env` 里再加
    一行 `GRASS_BRIDGE_BIN` 指向 grass 启动器完整路径。
- **`command` 跨平台替换**：示例写 `python`，适合多数
  Windows Python 安装。macOS/Linux 若只有 `python3`，把
  `command` 改为 `python3`。Windows 若只有 Python
  Launcher，把 `command` 改为 `py`，并在 `args` 数组最
  前面加一个 `"-3"` 元素。
- **token 配置不在 JSON 示例里是刻意的**：二选一——
  (1) 自己生成一个随机值，在客户端 `env` 里加
  `GRASS_BRIDGE_TOKEN` 并安全保存；或 (2) 不加这一项，
  让服务端首次启动时把随机 token 写到
  `~/.grass-agent-bridge.token`（Windows：
  `%USERPROFILE%\.grass-agent-bridge.token`），之后从该
  文件读取。无论哪种方式，服务端都**不会自动替调用方
  附带**：每次 tools/call 的 `arguments` 里都要有同一个
  `_token`，例如
  `{"_token":"<从 env 或 token 文件读到的值>", "location":"demo", "mapset":"user1"}`。
  完整示例见 `../live/HEADLESS.md`。真实 token 不要发到
  聊天、截图或仓库里。
- 无常驻应用内桥（stdio 直连，本包不监听网络端口）：MCP
  服务端用普通 Python 3 启动即可；token 守卫常开。
- 启动顺序：先配好 `GRASS_BRIDGE_GISDBASE`，跑一遍
  `live/selftest.py` 与 `scripts/probe_api.py` 留档，再
  注册服务端；注册或改 env 后要重启客户端拉起的服务端
  进程。

## 提示词示例（可直接对 Agent 说）

通用预期：Agent 应自行从已配置的 env 或 token 文件取得
`_token` 并在每次 tools/call 中附带，但不得在对话或回报
里回显真实值。执行/写类动作的 `confirm=true` 只能在本
次对话里得到用户明确同意后填入。

### 环境发现

> 用 grass_discover 看一下 GRASS 版本、数据库在哪、里面
> 有哪些 location。

预期行为：只读回报；GRASS 不可用会如实给出
GRASS_NOT_AVAILABLE，不粉饰。

### 看图层与栅格信息

> 用 grass 桥列一下 demo 的 user1 mapset 里的栅格，再看
> elevation 的范围和行列数。

预期行为：只读；图层名以 list 结果为准，不猜名。

### 跑一个处理作业（会触发 confirm 闸）

> 用 grass_run_module 在 demo/user1 里以 elevation 为
> 输入跑 slope_aspect，输出图层名用 slope1 和 aspect1。

预期行为：Agent 先复述作业与产出、等用户确认后才带
confirm=true 执行；输出名与已有图层重名导致 GRASS 失败时
如实回报，不自行换名重试。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具
定义一致；接入是否成功以工具真实返回为准，不要把协议
自检通过当作已在真实 GRASS GIS 上校准——校准状态见包内
docs/CALIBRATION.md。
