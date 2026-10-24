# ROADMAP —— arcmap-bridge-lite 说明与待校准清单

## 定位

ArcMap 已于 2026-03-01 被 Esri 退役（10.8.2 为最终版本）。本包是给
存量 ArcMap 用户的个人自用轻量版：范围刻意收窄，不做系列门面，
不规划功能扩张；后续只做实机校准收紧与缺陷修复。主力平台的新功能
请看 ArcGIS Pro 方向，不要往这个包里加。

## 版本

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.2 | selftest 改后台线程 + 队列读行（修 Windows select 等管道问题）；token 文件位置支持 ARCMAP_BRIDGE_TOKEN_FILE 环境变量覆盖（桥/MCP/selftest 三处一致）；新增 scripts/verify_project.py 只读盘点/迁移验收与 ENGINEERING-PLAYBOOK.md；serverInfo 版本升 0.2.0；工具清单（10 个）、端口 47617、confirm 闸与 BAD_TOKEN 语义不变 | VM 侧已验证：py_compile 全过、selftest 6/6 PASS、verify_project.py 无 arcpy 时结构化报错 + 退出码 1；**arcpy 实机路径仍未验证**，迁移口径见 docs/CALIBRATION.md 新增一节 |
| v0.1 | 无头桥三件只读动作（preflight 多策略定位 Desktop Python/arcpy、backup 含同名 .gdb 整体复制 + sha256、inspect 复制到临时目录盘点并标注 headless-saved-state）；校准探针 probe_api.py；实时桥：inapp_bridge.py 跑在 ArcMap Python 窗口内（Python 2.7/3.x 兼容子集，127.0.0.1:47617 + token + 文档多策略发现），mcp_server.py 为 Python 3 纯标准库 stdio 转发；10 个工具（6 只读 + 1 只读出文件 + 2 视图级 + 1 写类 confirm 闸）；一键自检 live/selftest.py | VM 侧（无 ArcMap）已验证：全部脚本 py_compile 通过；selftest 6/6 PASS（initialize / tools-list=10 / ping / discover 结构化回报 / 保存闸门 / 错误 token）；无头 preflight/inspect 在无 arcpy 时结构化报错 + 退出码 1；backup 用样例 .mxd 实测真复制 + sha256 一致、同名 .gdb 文件夹整体复制计数正确；**arcpy 实机路径与 Python 2.7 运行时未验证**，按 docs/CALIBRATION.md 校准 |

## 待实机校准清单（按依赖顺序）

1. **Python 2.7 运行时确认**：inapp_bridge.py 与两个 scripts/ 脚本在
   ArcMap 自带 Python 2.7 里无语法错误可运行（开发侧只过了 Python 3
   的 py_compile 与兼容子集静态自查）；execfile 注入后后台线程正常、
   控制台不阻塞。
2. **discover 钉死 CURRENT 策略**：Python 窗口里
   `arcpy.mapping.MapDocument("CURRENT")` 是否返回 GUI 里正打开的文档
   （用 document_info 的 file_path 与界面标题逐项对）。file-fallback 不算数。
3. **后台线程里的 arcpy 调用**：桥的工具在服务线程中执行 arcpy.mapping，
   ArcMap 的对象带 COM 背景——连续调用（含刷新 RefreshActiveView）是否
   稳定无挂起，是本包最大的实机未知数；结论必须写入校准回报。
4. **只读盘点字段形态**：DataFrame 的 extent/scale/spatialReference、
   Layer 的 dataSource/visible/isBroken、ListTableViews 的返回对象字段，
   与 inspect/实时只读工具的回报逐项对界面。
5. **export_map_image**：ExportToPNG 的真实参数形态（PAGE_LAYOUT 字符串 /
   数据框对象 / resolution 关键字哪条命中），以文件落盘 + 字节数 > 0 为准。
6. **zoom_to_layer / set_layer_visible**：df.extent 赋值后界面是否即时
   刷新、RefreshActiveView 命中模块（arcpy 还是 arcpy.mapping）、
   TOC 显隐同步情况。
7. **save_document**：mxd.save() 在 CURRENT 对象上的行为；仅在副本上验，
   且经用户确认；saveACopy 回退路径是否触发也要如实记录。
8. 每个工具的命中策略（via）回写收紧：把多策略顺序按实机结果排序或
   删减，并在对应工具 docstring 里注明实机版本（如 Desktop 10.8 +
   Python 2.7）。

## 不做的事项（明确排除，防范围蔓延）

- 不做图层增删、符号系统修改、地理处理工具调用等写业务动作。
- 不做 ArcMap 的 .NET Add-in 路线（成本与收益不匹配一个退役平台）。
- 不追求多版本 Desktop 兼容矩阵；以校准机器的版本为准并注明。
