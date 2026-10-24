# mapgis 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **必须替换**：args 里的 `<ABSOLUTE_PATH_TO_PACKAGE>` 换成本包在你机器上的绝对路径；command 的 `python` 换成能跑该包的解释器（实时包用普通 Python 3 即可，服务端只做转发；envi/fme/gm 的服务端须用能 import 厂商模块的解释器，见包内说明）。
- env 里的 `MAPGIS_BRIDGE_TOKEN_FILE` 是可选的 token 文件位置覆盖；不设置时用默认路径（家目录下点文件），桥与服务端两侧须保持一致。
- 无常驻应用内桥（stdio 直连/无头）
- 启动顺序：本包没有应用内桥：MapGIS 的应用内会话接口未经证实，本服务端只把探针能力包装成 MCP 工具。服务端启动时在 token 文件生成/读取本次 token；discover 与 probe_environment 调用时必须在 arguments 里带 token 字段（从 token 文件读），否则返回 BAD_TOKEN。

## 提示词示例（可直接对 Agent 说）

### 只读探针

> 先用 mapgis_ping 确认探针服务端在线。

预期行为：ping 为公开健康检查，不需要 token。

### 带 token 的发现

> 从 token 文件读出 token，用 mapgis_discover（arguments 带 token）告诉我本机有没有可用的 MapGIS Python 绑定。

预期行为：只读探针；token 不对会返回 BAD_TOKEN。

### 关于写操作

> 本包没有任何写类工具，也没有 confirm 场景：3 个工具全部是只读环境探针。将来实时桥路线证实后，写操作才会按本系列统一纪律加 confirm 闸。

预期行为：如实标注，不虚构写能力。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义一致；接入是否成功以工具真实返回为准，不要把协议自检通过当作已在真实软件上校准——校准状态见包内 docs/CALIBRATION.md。
