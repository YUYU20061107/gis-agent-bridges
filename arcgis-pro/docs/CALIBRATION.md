# 实机校准指南 —— arcgis-pro-bridge v0.1 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述要达成的结果、
验收标准与红线，具体做法由执行者决定；
但每一步的原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

前置条件：一台装有 ArcGIS Pro 3.x 且许可已登录可用的机器；
一份可弃用的测试工程（含至少 1 幅地图、若干图层、1 个布局）；
本指南的操作对象先是这份测试工程，后是用户工程的副本——原件永远不碰。

## 目标结果（全部达成才算完成）

1. 实时桥在目标机器的 ArcGIS Pro 上完成校准：`arcgis_discover` 的 mode 为
   `live:CURRENT` 或 `live:global:*`，且有证据表明桥接入的就是 GUI 里打开的
   那个工程（不是文件回退）。
2. 13 个 arcgis_* 工具（12 个工程工具 + ping）逐个有实机结论：
   可用（附命中策略 via 与回报 JSON）或不可用（附原始报错与现场方法清单线索），
   不许留"应该可以"式的模糊结论。
3. 写类工具全部在**工程副本**上验证通过后，才许对正式工程使用；
   验证过程对原件零写入（原件修改时间不变可查）。
4. 校准结论回写进代码：命中策略按实机结果收紧排序，工具 docstring 注明实机版本
   （ArcGIS Pro 版本 + arcpy 版本），并跑一遍 `live/selftest.py` 保持 6/6 PASS。

## 校准顺序（不要跳步）

0. **无头桥先行**：用 Pro 自带 Python 跑 preflight 与 probe_api.py，完整回传输出；
   对测试工程先 backup 再 inspect，把 inspect 结果与 Pro 里该工程的
   **已保存状态**逐项核对（注意：界面里故意留一处未保存修改，验证 inspect
   确实看不到它——看到的是存盘状态，这条核对通过才算口径成立）。
1. **先 discover 钉死实时工程策略**：按 live/LIVE.md 在 Pro 的 Python 窗口启动
   实时桥（有条件时再在 Notebook 里复验一遍），完整回传 discover 的 JSON
   （mode、attempts、mp_class_methods、main_globals）。mode 不是 `live:*` 就停
   在这里，先解决接入方式，不许往下走；同时记录后台线程调用 arcpy.mp 有无异常。
2. **只读工具对界面核对**：project_info、list_maps、list_layers、list_tables、
   list_layouts 的结果逐项与 Pro 界面里看到的对上，留文字或截图证据。
3. **操作工具逐个验（只在副本上）**，顺序：
   export_map_image → zoom_to_layer → set_layer_visible → set_labels_visible →
   add_layer_from_path → save_project 最后验，且调用前须经用户当场确认。
4. **收紧与回归**：按命中策略改代码并注明版本；跑 selftest；把改动点逐条列清回传。

## 每项验收标准

- discover：mode=`live:*`；attempts 里能看出命中的是哪条策略；Python 窗口与
  Notebook 两种会话的结论分别记录（哪种可用、哪种不可用，如实写）。
- 无头 inspect：回报与**已保存状态**一致，且确实不含预留的那处未保存修改；
  回报文本里带 headless-saved-state 口径说明。
- 只读类：回报 JSON 与界面所见一致（地图名、图层名与顺序、表名、布局名逐项对；
  断裂图层 is_broken 标记与界面红色感叹号对上）。
- export_map_image：目标路径真有 PNG 落盘、字节数 > 0、能打开且内容是当前布局/地图。
- zoom_to_layer：界面视图确实缩放到该图层范围（截图或文字描述前后范围）；无活动
  视图时工具如实报 NOT_SUPPORTED 也算该项结论成立（记录场景即可）。
- set_layer_visible：界面上目标图层随开关显隐，visible_now 与设置值一致。
- set_labels_visible：界面上目标图层标注随开关出现/消失，命中的是属性途径
  还是 CIM 途径要记清。
- add_layer_from_path：list_layers 复核图层数变化，界面里能看到新图层及其数据；
  layers_after 不可信时以界面为准并如实说明。
- save_project：仅在副本上、且经用户确认后调用；保存后重开副本核对改动在。

## 回报格式

每个工具一条：①一句话结论（可用/不可用）；②桥回报 JSON 原文；
③命中的策略（via 字段原文）；④界面证据（截图或具体文字）。
最后附：改动文件清单 + selftest 输出原文 + 仍未解决项清单。

## 红线（违反任意一条立即停下回报）

- **不碰无关环境**：不要使用、安装或修改与本任务无关的既有项目环境
  （包括其他 Conda 环境）；尤其**不许往 ArcGIS Pro 自带环境 arcgispro-py3 里
  pip 装包或改配置**，需要别的解释器跑 MCP 服务端时用系统现成的 Python 3 即可。
- **原件只读**：先用无头桥 backup，再复制出工作副本；一切写验证只在副本上做。
- **mode=file-fallback 必须如实说**，不许报成实时接入成功；拿不到进程内当前
  工程就停在校准第 1 步。无头 inspect 的结果必须标注"已保存状态"，不许说成实时。
- **写操作先确认**：add_layer_from_path、save_project 的 confirm=true 只能在
  用户明确同意后由你填入，不许自作主张绕过闸口。
- 许可/版本报错即停，回报原始报错全文，不许换版本、换环境反复试探。
- 不许自行扩展工具集或动作范围；**尤其不许临时加任意代码执行或任意 GP
  调用工具来"凑"校准结论**。发现 API 与脚本假设不符，回报现场方法清单，
  等维护者据实收紧，不要在实机临时发明新策略后当成定案。
