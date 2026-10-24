# fme 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **必须替换**：args 里的 `<ABSOLUTE_PATH_TO_PACKAGE>` 换成本包在你机器上的绝对路径；command 的 `python` 换成能跑该包的解释器（实时包用普通 Python 3 即可，服务端只做转发；envi/fme/gm 的服务端须用能 import 厂商模块的解释器，见包内说明）。
- 无常驻应用内桥（stdio 直连/无头）
- 启动顺序：本包是无头 runner（与官方 FME Flow MCP 的分工见 live/RUNNER.md）：MCP 服务端必须用能 import fmeobjects 的 Python 启动。可选 token 守卫：环境变量 FME_BRIDGE_TOKEN 或 token 文件，设置后 tools/call 须带匹配 token。

## 提示词示例（可直接对 Agent 说）

### 只读盘点

> 用 fme_list_workspaces 列出「<目录>」下的 .fmw，再用 fme_workspace_info 解析其中一个的源/目标数据集。

预期行为：只读文本尽力解析，结果可能不完整，会如实标注。

### 看日志

> 用 fme_workspace_log_tail 读「<workspace 路径>」最近一次运行日志的尾部 50 行。

预期行为：只读。

### 写操作（触发 confirm）

> 运行 workspace「<.fmw 路径>」，published parameters 用我给的这组。

预期行为：会调用 fme_run_workspace：执行类，必须带 confirm=true 才执行——运行 workspace 会按其定义真实读写数据。Agent 先复述路径与参数、取得用户明确同意再填 confirm。无 fmeobjects 时返回 FME_NOT_AVAILABLE。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义一致；接入是否成功以工具真实返回为准，不要把协议自检通过当作已在真实软件上校准——校准状态见包内 docs/CALIBRATION.md。
