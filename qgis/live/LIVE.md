# 实时桥使用说明（QGIS 应用内桥 + MCP 接入，v0.1）

架构（同 Blender MCP 的模式）：
QGIS 进程内跑一个桥脚本（拿到当前工程）→ 本机 127.0.0.1:47618 →
MCP 服务端（stdio）→ 你的 AI Agent 调用工具直接操作你正开着的工程，界面实时可见。

## 启动三步

1. 打开 QGIS，打开要操作的工程。
2. 打开 QGIS 的 Python 控制台（菜单「插件 → Python 控制台」，或 Ctrl+Alt+P），执行：
   `exec(open(r"<包路径>\live\inapp_bridge.py", encoding="utf-8").read())`
   看到 `[qgis-live-bridge] listening on 127.0.0.1:47618` 即桥已上线；
   它同时把本次 token 写到 `~/.qgis-live-bridge.token`，MCP 服务端自动读取，无需手填。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端（命令与参数按该客户端的配置格式填）：
   - command: 任意 Python 3 解释器（不需要装 QGIS，它只做转发）
   - args: `<包路径>\live\mcp_server.py`
   注册后客户端应能列出 12 个 qgis_* 工具。

接入前可先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token 共 6 项，
全 PASS 才说明包本身没坏；它不验证与 QGIS 本体的对接，无 QGIS 也能跑）。

## 工具清单（v0.1，共 12 个）

风险等级：只读＝无副作用；视图级＝只改显示状态、可逆、不落盘；
写/执行类＝改变工程内容或运行算法，全部带 confirm=true 闸（confirm 只能在用户明确同意后填）。

| 工具 | 作用 | 风险 |
|---|---|---|
| qgis_ping | 桥是否在线 | 只读 |
| qgis_discover | 发现当前工程接入方式 + 现场 API 清单（校准用） | 只读 |
| qgis_project_info | 当前工程概览（标题/路径/工程 CRS/图层数/接入模式） | 只读 |
| qgis_list_layers | 列图层（名称、数据源、CRS、显隐；经图层树带顺序与分组） | 只读 |
| qgis_list_layouts | 列打印布局名 | 只读 |
| qgis_list_fields | 列某矢量图层的字段（名称、类型、长度） | 只读 |
| qgis_export_map_image | 导出地图/布局为图片（以文件真落盘且字节>0 为准） | 只读出文件 |
| qgis_set_layer_visible | 设置图层显隐 | 视图级 |
| qgis_zoom_to_layer | 画布缩放到图层范围；无画布时报 NOT_SUPPORTED 并附范围 | 视图级 |
| qgis_add_layer_from_path | 按路径加载图层并加入工程（须 confirm=true） | **写** |
| qgis_run_processing | 运行 Processing 算法，只接受算法 id＋参数 JSON（须 confirm=true） | **执行** |
| qgis_save_project | 保存当前工程（须 confirm=true） | **写** |

12 个工具**全部为实验性实现，未在真实 QGIS 上验证**：PyQGIS 各版本的图层树
显隐 API 命名、Qt 主线程调度、Processing 加载方式与布局导出签名都有差异，
桥用多策略尝试并在结果里回报命中的策略（via）与调度方式（dispatch）；
拿不到对象或 API 不匹配时返回结构化错误（NOT_SUPPORTED / *_FAILED，
附现场方法清单线索），这属于预期行为，Agent 必须如实回报，不许粉饰成成功。
首次实机校准按 `docs/CALIBRATION.md` 的顺序逐项进行（先 discover 钉死策略，
写/执行类工具只在工程副本上验）。

**刻意不提供任意代码执行工具**：run_processing 只接受算法 id 与参数对象，
这是有意的安全取舍。算法 id 与参数在执行前应由用户复核，不许拿它当代码执行后门。

## 纪律

- 桥只监听 127.0.0.1 且带 token，不要改成对外监听，不要把 token 发给任何人。
- discover 的结果是判断"接入是否真的是 GUI 里那个工程"的依据：
  若 mode 显示 file-fallback，说明走的是文件回退（仅文件解析盘点），
  操作不会实时反映到界面，必须如实回报用户，不许说成实时接入。
- 写/执行类工具的 confirm=true 只能在用户明确同意后由 Agent 填入，不许自作主张绕过。
- QGIS 里若弹出模态对话框（如未保存提示），主线程会被阻塞，工具可能超时——
  先处理弹窗再重试，不要连环重试。

## 首次校准工单（给执行校准的 AI Agent，可直接粘贴）

> 按 `<包路径>\live\LIVE.md` 启动实时桥并完成校准。目标结果：(1) qgis_ping 通；
> (2) qgis_discover 完整回报（mode、attempts、dispatch、processing_available、
> project_methods、main_globals 原样回传）；(3) qgis_project_info、qgis_list_layers、
> qgis_list_layouts 的结果与 QGIS 界面里看到的一致，并截图或文字确认界面里
> 打开的正是同一个工程。mode 若为 file-fallback 就直说，不许报成实时接入成功。
> 全程除非我点名，不许调用任何写/执行类工具（add_layer_from_path、
> run_processing、save_project）。后续逐项校准操作工具时改按 docs/CALIBRATION.md 执行。
