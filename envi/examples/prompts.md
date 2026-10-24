# envi 客户端接入示例

- 配置文件：同目录 `mcp-client-config.json`，把内容合并进你的 MCP 客户端配置（如 Claude Desktop / Cursor / Trae 的 mcpServers 段）。
- **必须替换**：args 里的 `<ABSOLUTE_PATH_TO_PACKAGE>` 换成本包在你机器上的绝对路径；command 的 `python` 换成能跑该包的解释器（实时包用普通 Python 3 即可，服务端只做转发；envi/fme/gm 的服务端须用能 import 厂商模块的解释器，见包内说明）。
- 无常驻应用内桥（stdio 直连/无头）
- 启动顺序：本包只有无头桥（原因见 live/HEADLESS.md）：MCP 服务端用能 import idlpy 的 Python 启动；.hdr 盘点不依赖 ENVI 安装，真跑任务时才惰性启动无头 ENVI 会话。可选安全闸：设置环境变量 ENVI_BRIDGE_TOKEN 后，tools/call 须在 arguments 里带匹配 token。

## 提示词示例（可直接对 Agent 说）

### 只读盘点

> 用 envi_raster_info 盘点「<栅格 .hdr 路径>」，先走 .hdr 解析告诉我波段、尺寸和数据类型。

预期行为：只读；无 ENVI 时也会如实返回结构化结果。

### 任务查询

> 用 envi_list_tasks 看本机 ENVI 有哪些 ENVITask，再用 envi_describe_task 描述「<任务名>」的参数。

预期行为：只构造任务对象读参数，不执行。

### 写操作（触发 confirm）

> 用任务「<任务名>」处理「<输入栅格>」，输出到「<新文件路径>」。

预期行为：会调用 envi_run_task：写类，必须带 confirm=true 才执行。Agent 先复述任务与输出路径、取得用户明确同意再填 confirm。无 ENVI 时返回 ENVI_NOT_AVAILABLE，不假装成功。

注：示例中的工具名均与本包 live/mcp_server.py 的实际工具定义一致；接入是否成功以工具真实返回为准，不要把协议自检通过当作已在真实软件上校准——校准状态见包内 docs/CALIBRATION.md。
