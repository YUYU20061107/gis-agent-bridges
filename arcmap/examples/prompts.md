# arcmap 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **必须替换**：args 里的 `<ABSOLUTE_PATH_TO_PACKAGE>` 换成本包在你机器上的绝对路径；command 的 `python` 换成能跑该包的解释器（实时包用普通 Python 3 即可，服务端只做转发；envi/fme/gm 的服务端须用能 import 厂商模块的解释器，见包内说明）。
- env 里的 `ARCMAP_BRIDGE_TOKEN_FILE` 是可选的 token 文件位置覆盖；不设置时用默认路径（家目录下点文件），桥与服务端两侧须保持一致。
- 应用内桥端口：127.0.0.1:47617
- 启动顺序：先按 live/LIVE.md 在 ArcMap 里启动应用内桥（ArcMap 已被 Esri 退役，本包为个人自用向），桥会生成随机 token 并写入 token 文件，MCP 服务端自动读取。

## 提示词示例（可直接对 Agent 说）

### 只读盘点

> 先用 arcmap_ping 确认桥在线，再用 arcmap_document_info 和 arcmap_list_layers 告诉我当前地图文档里有哪些数据框和图层。

预期行为：全程只读。

### 导出成图

> 用 arcmap_export_map_image 把当前文档导出为 PNG 到我指定的路径，以文件真实落盘为准回报。

预期行为：导出写新文件，按现行设计无 confirm 闸，路径由用户明确给出。

### 写操作（触发 confirm）

> 保存当前地图文档。

预期行为：会调用 arcmap_save_document：写操作，必须带 confirm=true 才执行。Agent 先取得用户明确同意再填 confirm。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义一致；接入是否成功以工具真实返回为准，不要把协议自检通过当作已在真实软件上校准——校准状态见包内 docs/CALIBRATION.md。
