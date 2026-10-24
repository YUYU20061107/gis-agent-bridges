# 实机校准指南 —— arcmap-bridge-lite v0.1 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述要达成的结果、
验收标准与红线，具体做法由执行者决定；
但每一步的原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

背景现实（校准前先对齐）：ArcMap 已于 2026-03-01 被 Esri 退役，本包是
个人自用轻量版，校准目标是"在我这台机器的 ArcMap 上可用且行为可预期"，
不是产品级兼容矩阵。另外，桥脚本跑在 ArcMap 的 **Python 2.7** 里，
开发环境的 Python 3 自检只能证明协议层没坏，2.7 运行时行为必须实机确认。

## 目标结果（全部达成才算完成）

1. 无头桥在目标机器上跑通：preflight 用 Desktop 自带 Python 回报 arcpy
   可导入与确切版本；probe_api.py 输出完整回传；任选一个真实 .mxd 完成
   backup + inspect，inspect 内容与 ArcMap 里打开所见一致。
2. 实时桥完成校准：`arcmap_discover` 的 mode 为 `live:CURRENT`（或
   `live:global:*`），且有证据表明桥接入的就是 GUI 里打开的那个文档
   （不是文件回退）。
3. 10 个 arcmap_* 工具逐个有实机结论：可用（附命中策略 via 与回报 JSON）
   或不可用（附原始报错与现场方法清单线索），不许留"应该可以"式的模糊结论。
4. 写操作（save_document）只在**文档副本**上验证通过，且调用前经用户
   当场确认；验证过程对原件零写入（原件修改时间不变可查）。
5. 校准结论回写进代码：命中策略按实机结果收紧排序，工具 docstring 注明
   实机版本（Desktop 版本 + Python 版本），并跑一遍 `live/selftest.py`
   保持 6/6 PASS。

## 校准顺序（不要跳步）

1. **无头桥先行**：用 `C:\Python27\ArcGIS10.x\python.exe` 跑 preflight 与
   probe_api.py，确认 arcpy 版本线；再对一个真实 .mxd 跑 backup + inspect，
   与界面逐项核对（数据框名、图层名、断裂标记、页面大小）。
2. **discover 钉死实时文档策略**：打开 ArcMap 与目标文档，按 live/LIVE.md
   用 execfile 注入桥，完整回传 discover 的 JSON（mode、attempts、
   document_methods、mapping_names、main_globals）。mode 不是 `live:*`
   就停在这里，先解决接入方式，不许往下走。同时确认：桥在 Python 2.7
   窗口里无语法/导入错误、后台线程已起、控制台未被阻塞。
3. **只读工具对界面核对**：document_info、list_dataframes、list_layers、
   list_tables 的结果逐项与 ArcMap 界面里看到的对上，留文字或截图证据。
4. **操作工具逐个验（只在副本上）**，顺序：
   export_map_image → zoom_to_layer → set_layer_visible → save_document
   最后验，且调用前须经用户当场确认。
5. **收紧与回归**：按命中策略改代码并注明版本；跑 selftest；
   把改动点逐条列清回传。

## 每项验收标准

- discover：mode=`live:CURRENT` 或 `live:global:*`；attempts 里能看出命中的是哪条策略。
- 只读类：回报 JSON 与界面所见一致（文档路径、数据框名、图层名逐项对）。
- export_map_image：目标路径真有 PNG 落盘、字节数 > 0、能打开且内容是当前文档
  （布局视图出整页、数据视图出当前范围，以回报 via 注明的策略为准）。
- zoom_to_layer：界面视图确实缩放到该图层范围（截图或文字描述前后范围）。
- set_layer_visible：界面上目标图层随开关显隐，visible_now 与设置值一致，
  且内容列表（TOC）同步刷新。
- save_document：仅在副本上、且经用户确认后调用；保存后重开副本核对改动在。
- 线程行为：连续调用多个工具无挂起、无 COM 类异常；若出现，记为未解决项
  并注明复现步骤，不要反复重试。

## 回报格式

每个工具一条：①一句话结论（可用/不可用）；②桥回报 JSON 原文；
③命中的策略（via 字段原文）；④界面证据（截图或具体文字）。
最后附：改动文件清单 + selftest 输出原文 + 仍未解决项清单
（务必单列 Python 2.7 运行时与后台线程两项的实机结论）。

## 红线（违反任意一条立即停下回报）

- **不碰无关环境**：不要使用、安装或修改与本任务无关的既有项目环境
  （解释器环境、依赖与配置）；尤其不要试图给普通 Python 3 pip 安装 arcpy。
- **原件只读**：先用无头桥 backup，再复制出工作副本；一切写验证只在副本上做。
- **mode=file-fallback 必须如实说**，不许报成实时接入成功；
  拿不到实时对象就停在校准第 2 步。
- **写操作先确认**：save_document 的 confirm=true 只能在用户明确同意后
  由你填入，不许自作主张绕过闸口。
- 许可/版本报错即停，回报原始报错全文，不许换版本、换环境反复试探。
- 不许自行扩展工具集或动作范围；发现 API 与脚本假设不符，回报现场
  方法清单，等维护者据实收紧，不要在实机临时发明新策略后当成定案。
