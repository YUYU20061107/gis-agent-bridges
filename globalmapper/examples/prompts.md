# globalmapper 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **必须替换**：args 里的 `<ABSOLUTE_PATH_TO_PACKAGE>` 换成本包在你机器上的绝对路径；command 的 `python` 换成能跑该包的解释器（实时包用普通 Python 3 即可，服务端只做转发；envi/fme/gm 的服务端须用能 import 厂商模块的解释器，见包内说明）。
- 无常驻应用内桥（stdio 直连/无头）
- 启动顺序：本包在 Global Mapper 提供的 Python 上下文里直接 import globalmapper 模块（仅 Pro 版提供），无常驻应用内桥进程。可选安全闸：设置环境变量 GM_BRIDGE_TOKEN 后，tools/call 须在 arguments 里带匹配的 _token。

## 提示词示例（可直接对 Agent 说）

### 只读盘点

> 先用 globalmapper_ping 确认模块可用性，再用 globalmapper_list_layers 列出当前已加载的图层。

预期行为：只读。

### 导出成图

> 用 globalmapper_export_workspace_image 把当前图层导出为栅格图片到我指定的路径，以文件落盘且字节>0 为准回报。

预期行为：导出写新文件，按现行设计无 confirm 闸，路径由用户明确给出；视图级工具（set_layer_visible 等）在无头脚本上下文会返回 NOT_IN_MAIN_VIEW_CONTEXT，不冒充已执行。

### 关于写操作

> 本包没有 confirm 类写工具：能改的只有视图状态（且限主视图上下文），其余为只读盘点与导出。

预期行为：如实标注，不虚构写能力。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义一致；接入是否成功以工具真实返回为准，不要把协议自检通过当作已在真实软件上校准——校准状态见包内 docs/CALIBRATION.md。
