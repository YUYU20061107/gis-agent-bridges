# 实机校准指南 —— qgis-bridge v0.1 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述要达成的结果、
验收标准与红线，具体做法由执行者决定；
但每一步的原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

## 目标结果（全部达成才算完成）

1. 实时桥在目标机器的 QGIS 上完成校准：`qgis_discover` 的 mode 为 `live:*`，
   且有证据表明桥接入的就是 GUI 里打开的那个工程（不是文件回退）。
2. 12 个 qgis_* 工具逐个有实机结论：可用（附命中策略 via 与回报 JSON）或
   不可用（附原始报错与现场方法清单线索），不许留"应该可以"式的模糊结论。
3. 写/执行类工具全部在**工程副本**上验证通过后，才许对正式工程使用；
   验证过程对原件零写入（原件修改时间不变可查）。
4. 校准结论回写进代码：命中策略按实机结果收紧排序，工具 docstring 注明实机版本
   （QGIS 版本），并跑一遍 `live/selftest.py` 保持 6/6 PASS。

## 校准顺序（不要跳步）

1. **先 discover 钉死实时工程策略**：启动 QGIS 与实时桥（按 live/LIVE.md），
   完整回传 discover 的 JSON（mode、attempts、dispatch、processing_available、
   project_methods、main_globals）。mode 不是 `live:*` 就停在这里，
   先解决接入方式，不许往下走。dispatch 是 qt-main-thread 还是 worker-thread
   一并记录，它是后续稳定性的判读依据。
2. **只读工具对界面核对**：project_info、list_layers、list_layouts、list_fields
   的结果逐项与 QGIS 界面里看到的对上，留文字或截图证据。
3. **操作工具逐个验（只在副本上）**，顺序：
   export_map_image → zoom_to_layer → set_layer_visible → add_layer_from_path
   → run_processing（只许用无害算法，如对测试图层做 native:buffer 输出到临时层；
   算法与参数须先经用户复核）→ save_project 最后验，
   且调用前须经用户当场确认。
4. **无头侧对账**：对同一工程分别跑 inspect 的 parse 与 qgis 两种策略，
   图层清单逐项对账，差异如实记录。
5. **收紧与回归**：按命中策略改代码并注明版本；跑 selftest；把改动点逐条列清回传。

## 每项验收标准

- discover：mode=`live:*`；attempts 里能看出命中的是哪条策略；dispatch 有明确值。
- 只读类：回报 JSON 与界面所见一致（图层名、顺序、分组、显隐、数据源逐项对）。
- export_map_image：目标路径真有图片落盘、字节数 > 0、能打开且内容是当前地图/布局。
- zoom_to_layer：界面画布确实缩放到该图层范围（截图或文字描述前后范围）。
- set_layer_visible：界面上目标图层随开关显隐，visible_now 与设置值一致。
- add_layer_from_path：list_layers 复核图层数变化，界面里能看到新图层；
  layers_after 不可信时以界面为准并如实说明。
- run_processing：算法真实执行、结果与回报一致；输出只许落在临时层或工程副本内，
  不许对原件数据做原地改写类算法。
- save_project：仅在副本上、且经用户确认后调用；保存后重开副本核对改动在。

## 回报格式

每个工具一条：①一句话结论（可用/不可用）；②桥回报 JSON 原文；
③命中的策略（via / dispatch 字段原文）；④界面证据（截图或具体文字）。
最后附：改动文件清单 + selftest 输出原文 + 仍未解决项清单。

## 红线（违反任意一条立即停下回报）

- **不碰无关环境**：不要使用、安装或修改与本任务无关的既有项目环境（解释器环境、依赖与配置）；需要 QGIS 的 Python 时用 QGIS 自带解释器，不要往无关环境里 pip 装东西凑。
- **原件只读**：先用无头桥 backup，再复制出工作副本；一切写验证只在副本上做。
- **mode=file-fallback 必须如实说**，不许报成实时接入成功；拿不到实时对象就停在校准第 1 步。
- **写/执行操作先确认**：add_layer_from_path、run_processing、save_project 的
  confirm=true 只能在用户明确同意后由你填入，不许自作主张绕过闸口；
  run_processing 的算法 id 与参数必须先给用户看过。
- **不许新增任意代码执行入口**：不许为了校准临时加 exec/eval/任意脚本类工具；
  发现 API 与脚本假设不符，回报现场方法清单，等维护者据实收紧。
- 版本报错即停，回报原始报错全文，不许换版本、换环境反复试探。
- 不许自行扩展工具集或动作范围。
