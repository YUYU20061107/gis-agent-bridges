# 实时桥使用说明（ArcMap 应用内桥 + MCP 接入，v0.1）

架构（同 Blender MCP 的模式）：
ArcMap 进程内的 Python 窗口里跑一个桥脚本（经 `MapDocument("CURRENT")`
拿到当前文档）→ 本机 127.0.0.1:47617 → MCP 服务端（Python 3，stdio）→
你的 AI Agent 调用工具直接操作你正开着的地图文档，界面实时可见。
端口与同系列桥错开：SuperMap 47615、ArcGIS Pro 47616、本包 47617。

注意运行时差异：桥脚本跑在 ArcMap 自带的 **Python 2.7** 里（兼容子集
写法）；MCP 服务端跑在进程外，用任意 Python 3。两者不要混淆。

## 启动三步

1. 打开 ArcMap，打开要操作的地图文档。
2. 打开 ArcMap 的 Python 窗口（Geoprocessing 菜单 → Python 窗口），执行：
   `execfile(r"<包路径>\live\inapp_bridge.py")`
   - 看到 `[arcmap-live-bridge] listening on 127.0.0.1:47617` 即桥已上线；
     它同时把本次 token 写到 `~/.arcmap-live-bridge.token`，
     MCP 服务端自动读取，无需手填。
   - 桥以**后台线程**方式启动（注入时 `__file__` 不存在即自动走后台），
     Python 窗口不会被阻塞。若想显式控制，可先设环境变量
     `ARCMAP_BRIDGE_BLOCKING=0` 再注入。
   - 若窗口里的 Python 是 3.x 风格控制台（罕见），`execfile` 不可用时改用
     `exec(open(r"<路径>", encoding="utf-8").read())`。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端（命令与参数按该客户端的配置格式填）：
   - command: 任意 Python 3 解释器（不需要 arcpy，它只做转发）
   - args: `<包路径>\live\mcp_server.py`
   注册后客户端应能列出 10 个 arcmap_* 工具。

接入前可先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token 共 6 项，
全 PASS 只说明包的协议层没坏；它不验证与 ArcMap 本体的对接，
尤其不验证 Python 2.7 运行时——那一步必须在实机窗口里做，见校准指南）。

## 工具清单（v0.1，共 10 个）

风险等级：只读＝无副作用；视图级＝只改显示状态、可逆、不落盘；
写类＝改变文档内容，带 confirm=true 闸（confirm 只能在用户明确同意后填）。

| 工具 | 作用 | 风险 |
|---|---|---|
| arcmap_ping | 桥是否在线 | 只读 |
| arcmap_discover | 发现当前文档接入方式 + 现场 API 清单（校准用） | 只读 |
| arcmap_document_info | 当前文档概览（路径/活动视图/页面大小/数据框数/图层数） | 只读 |
| arcmap_list_dataframes | 列数据框（名称、范围、比例尺、空间参考、图层数） | 只读 |
| arcmap_list_layers | 列图层（下标/名称/数据源/显隐/断裂，可按数据框过滤） | 只读 |
| arcmap_list_tables | 列独立表视图（名称、数据源） | 只读 |
| arcmap_export_map_image | 导出当前文档为 PNG 到指定路径（以文件真落盘为准） | 只读出文件 |
| arcmap_set_layer_visible | 设置图层显隐（设置后尝试刷新活动视图） | 视图级 |
| arcmap_zoom_to_layer | 数据框视图缩放到图层范围并刷新 | 视图级 |
| arcmap_save_document | 保存当前文档（须 confirm=true） | **写** |

全部工具均为**未在真实 ArcMap 上验证**的实现：arcpy.mapping 在不同
Desktop 小版本上属性命名大体稳定，但 `MapDocument("CURRENT")` 的可用性、
后台线程里调用 arcpy 的 COM 行为、ExportToPNG 的参数形态等都须实机
确认。桥用多策略尝试并在结果里回报命中的策略（via）；调不通时返回
结构化错误（NOT_SUPPORTED / *_FAILED，附现场方法清单线索），这属于
预期行为，Agent 必须如实回报，不许粉饰成成功。首次实机使用按
`docs/CALIBRATION.md` 的顺序逐项校准（先 discover 钉死 CURRENT，
操作工具只在文档副本上验）。

## 纪律

- 桥只监听 127.0.0.1 且带 token，不要改成对外监听，不要把 token 发给任何人。
- discover 的结果是判断"接入是否真的是 GUI 里那个文档"的依据：
  若 mode 显示 file-fallback，说明走的是文件回退（环境变量
  ARCMAP_LIVE_MXD_PATH），操作只影响桥打开的那个文件对象，
  不保证与界面同步，必须如实回报用户，不许说成实时接入。
- 写类工具的 confirm=true 只能在用户明确同意后由 Agent 填入，不许自作主张绕过。
- ArcMap 里若弹出未保存提示等 GUI 阻塞，工具会超时——先处理弹窗再重试，不要连环重试。
- 工具在桥的后台线程里执行 arcpy 调用；若出现 COM 类异常或挂起，
  先记为校准发现并停下，不要反复重试把 ArcMap 搞死。

## 首次校准工单（给执行校准的 AI Agent，可直接粘贴）

> 按 `<包路径>\live\LIVE.md` 启动实时桥并完成校准。目标结果：(1) arcmap_ping 通；
> (2) arcmap_discover 完整回报（mode、attempts、document_methods、mapping_names、
> main_globals 原样回传）；(3) arcmap_document_info、arcmap_list_dataframes、
> arcmap_list_layers 与 arcmap_list_tables 的结果与 ArcMap 界面里看到的一致，
> 并截图或文字确认界面里打开的正是同一个文档。mode 若为 file-fallback 就直说，
> 不许报成实时接入成功。全程除非我点名，不许调用 save_document。
> 后续逐项校准操作工具时改按 docs/CALIBRATION.md 执行。
