# 实机校准指南 —— supermap-gis-bridge v0.3 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述要达成的结果、
验收标准与红线，具体做法由执行者决定；
但每一步的原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

## 目标结果（全部达成才算完成）

1. 实时桥在目标机器的 iDesktopX 上完成校准：`supermap_discover` 的 mode 为 `live:*`，
   且有证据表明桥接入的就是 GUI 里打开的那个工作空间（不是文件回退）。
2. 13 个 supermap_* 工具逐个有实机结论：可用（附命中策略 via 与回报 JSON）或
   不可用（附原始报错与现场方法清单线索），不许留"应该可以"式的模糊结论。
3. 操作类工具全部在**工作空间副本**上验证通过后，才许对正式工程使用；
   验证过程对原件零写入（原件修改时间不变可查）。
4. 校准结论回写进代码：命中策略按实机结果收紧排序，工具 docstring 注明实机版本
   （iDesktopX 版本 + iobjectspy 版本），并跑一遍 `live/selftest.py` 保持 6/6 PASS。

## 校准顺序（不要跳步）

1. **先 discover 钉死实时工作空间策略**：启动 iDesktopX 与实时桥（按 live/LIVE.md），
   完整回传 discover 的 JSON（mode、attempts、workspace_methods、map_class_methods、
   main_globals）。mode 不是 `live:*` 就停在这里，先解决接入方式，不许往下走。
2. **只读工具对界面核对**：workspace_info、list_datasources、list_datasets、
   list_maps、list_layers 的结果逐项与 iDesktopX 界面里看到的对上，留文字或截图证据。
3. **操作工具逐个验（只在副本上）**，顺序：
   export_map_image → zoom_to_dataset → set_layer_visible → add_dataset_to_map →
   make_label_thematic（字段用数据集真实字段，如 NAME）→ save_workspace 最后验，
   且调用前须经用户当场确认。
4. **收紧与回归**：按命中策略改代码并注明版本；跑 selftest；把改动点逐条列清回传。

## 每项验收标准

- discover：mode=`live:*`；attempts 里能看出命中的是哪条策略。
- 只读类：回报 JSON 与界面所见一致（数据源别名、数据集名、地图名、图层名逐项对）。
- export_map_image：目标路径真有 PNG 落盘、字节数 > 0、能打开且内容是当前地图。
- zoom_to_dataset：界面视图确实缩放到该数据集范围（截图或文字描述前后范围）。
- set_layer_visible：界面上目标图层随开关显隐，visible_now 与设置值一致。
- add_dataset_to_map：list_layers 复核图层数变化，界面里能看到新图层；
  layers_after 不可信时以界面为准并如实说明。
- make_label_thematic：界面上出现该字段的标签专题，字段名大小写与数据集字段一致。
- save_workspace：仅在副本上、且经用户确认后调用；保存后重开副本核对改动在。

## 回报格式

每个工具一条：①一句话结论（可用/不可用）；②桥回报 JSON 原文；
③命中的策略（via 字段原文）；④界面证据（截图或具体文字）。
最后附：改动文件清单 + selftest 输出原文 + 仍未解决项清单。

## 红线（违反任意一条立即停下回报）

- **不碰无关环境**：不要使用、安装或修改与本任务无关的既有项目环境（解释器环境、依赖与配置）。
- **原件只读**：先用无头桥 backup，再复制出工作副本；一切写验证只在副本上做。
- **mode=file-fallback 必须如实说**，不许报成实时接入成功；拿不到实时对象就停在校准第 1 步。
- **写操作先确认**：add_dataset_to_map、make_label_thematic、save_workspace 的
  confirm=true 只能在用户明确同意后由你填入，不许自作主张绕过闸口。
- 许可/版本报错即停，回报原始报错全文，不许换版本、换环境反复试探。
- 不许自行扩展工具集或动作范围；发现 API 与脚本假设不符，回报现场方法清单，
  等维护者据实收紧，不要在实机临时发明新策略后当成定案。
