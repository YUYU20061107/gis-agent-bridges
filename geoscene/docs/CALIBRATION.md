# 实机兼容性核验与校准指南 —— geoscene-bridge v0.1

这是一份结果式指南，交给在实机上执行核验的 AI Agent：只描述要达成的结果、
验收标准与红线，具体做法由执行者决定；
但每一步的原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

## ⚠️ 本包的第一使命是核验，不是使用

> **本包与 GeoScene Pro 的兼容性是基于厂商"共用 ArcPy 内核"表述的推断，
> 未经任何实机验证。** 本包由同合集仓的 arcgis-pro-bridge 逐文件衍生，
> 桥内每一个 API 假设都来自 ArcGIS Pro 的形态。本指南要做的，就是在真实
> GeoScene Pro 上把这些假设逐项证实或证伪，并留下证据。在核验走完之前：
> 不许把本包当作可用工具对正式工程使用写类工具；不许拿 ArcGIS Pro 上的
> 任何结论冒充 GeoScene 的验证结果；核验不通过的项如实记录，就是本轮
> 最有价值的产出。

前置条件：一台装有 GeoScene Pro 且许可已登录可用的机器；
一份可弃用的测试工程（含至少 1 幅地图、若干图层、1 个布局）；
本指南的操作对象先是这份测试工程，后是用户工程的副本——原件永远不碰。

## 兼容性核验对照表（逐项打勾，不许跳项）

下表与来源包（Pro 版）已知的未验证项逐项对应。每项给出 GeoScene 上的
核验动作与通过标准；结论栏填写：✅ 通过（附证据编号）／❌ 不通过（附原始
报错）／⏸ 未验（附原因）。**第 0 项不通过，其余项全部暂停。**

| # | 核验项（对应来源包未验证项） | 核验动作 | 通过标准 |
|---|---|---|---|
| ☐ 0 | **产品身份**（本包特有前置项） | 用 GeoScene Pro 自带 Python 跑 preflight 与 probe_api.py | `product_clue.looks_like` 为 GeoScene，且 ProductName / InstallDir 原文留档；若显示连上的是 Esri ArcGIS 的 arcpy，本轮核验对象即告错误，停 |
| ☐ 1 | discover 钉死实时工程策略 | 在 GeoScene Pro 的 Python 窗口启动实时桥跑 discover；有条件时在 Notebook 再复验一遍 | mode 为 `live:CURRENT` 或 `live:global:*`；有证据表明接入的就是 GUI 里打开的那个工程；两种会话结论分别记录；桥的后台线程调用 arcpy.mp 无线程相关异常 |
| ☐ 2 | preflight / inspect 实机口径 | 对测试工程先 backup 再 inspect；界面里故意留一处未保存修改 | preflight 的 Version/LicenseLevel 与 GeoScene Pro 的"关于"一致；inspect 盘点（地图/图层/表/布局、断裂图层标记）与**已保存状态**逐项对上，且确实看不到预留的未保存修改；组图层、独立表、相对路径数据源的报告属实 |
| ☐ 3 | set_layer_visible / set_labels_visible | 在副本上逐个调用，观察界面 | visible / showLabels 属性赋值即时反映到界面；属性途径失败时 CIM 回写（getDefinition 的版本字符串 V2/V3、showLabels 在 CIM 中的确切位置）哪条命中，记录并回写代码、注明 GeoScene Pro 版本 |
| ☐ 4 | zoom_to_layer | 地图视图/布局视图/无视图三态各调一次 | activeView 可用性逐态有结论；camera.setExtent 与 camera.extent 赋值哪条命中；Describe(layer).extent 对栅格、注记、组图层的可得性边界有记录 |
| ☐ 5 | export_map_image | 对布局、地图框各导一次 PNG | Layout.exportToPNG 的真实签名（分辨率参数位置）确认；MapFrame.exportToPNG 的存在性与宽高参数确认；导出文件落盘、字节>0、能打开、内容与界面一致 |
| ☐ 6 | add_layer_from_path | 在副本上加入 shp / gdb 要素类 / 栅格 / .lyrx | Map.addDataFromPath 的返回对象与图层落位（顶部/底部）有结论；layers_after 计数是否可信有结论，不可信时文档回写"以界面为准"口径 |
| ☐ 7 | save_project | 仅在副本上、经用户当场确认后调用 | 保存成功；重开副本核对改动在；file-fallback 模式下 save 保存目标与界面工程不是同一个时，回报口径足够醒目 |
| ☐ 8 | 命中策略回写收紧 + 回归 | 按 1–7 的实机结果改代码并跑 live/selftest.py | 多策略顺序按实机结果排序或删减；各工具 docstring 注明实机版本（GeoScene Pro 版本 + arcpy 版本）；selftest 保持 6/6 PASS |

## 核验顺序（不要跳步）

0. **产品身份先行**（对照表第 0 项）：跑 preflight 与 probe_api.py，
   完整回传输出，先确认连上的是 GeoScene 的 arcpy。
1. **无头桥核对**（第 2 项）：对测试工程 backup → inspect，与已保存状态逐项对。
2. **discover 钉死实时策略**（第 1 项）：按 live/LIVE.md 在 GeoScene Pro 的
   Python 窗口启动实时桥，完整回传 discover 的 JSON（mode、attempts、
   mp_class_methods、main_globals、product_name、install_dir）。
   mode 不是 `live:*` 就停在这里，先解决接入方式，不许往下走。
3. **只读工具对界面核对**：project_info、list_maps、list_layers、list_tables、
   list_layouts 的结果逐项与 GeoScene Pro 界面里看到的对上，留文字或截图证据。
4. **操作工具逐个验（只在副本上）**，顺序：
   export_map_image → zoom_to_layer → set_layer_visible → set_labels_visible →
   add_layer_from_path → save_project 最后验，且调用前须经用户当场确认。
5. **收紧与回归**（第 8 项）：按命中策略改代码并注明版本；跑 selftest；
   把改动点逐条列清回传。

## 每项验收标准

- 产品身份：product_clue 与 probe 的 PRODUCT CLUE 两行一致指向 GeoScene；
  三者（preflight、probe、discover 的 product_name）互相印证。
- discover：mode=`live:*`；attempts 里能看出命中的是哪条策略；Python 窗口与
  Notebook 两种会话的结论分别记录（哪种可用、哪种不可用，如实写）。
- 无头 inspect：回报与**已保存状态**一致，且确实不含预留的那处未保存修改；
  回报文本里带 headless-saved-state 口径说明。
- 只读类：回报 JSON 与界面所见一致（地图名、图层名与顺序、表名、布局名逐项对；
  断裂图层 is_broken 标记与界面提示对上）。
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

对照表逐项一条：①结论（通过/不通过/未验）；②桥回报 JSON 原文；
③命中的策略（via 字段原文）；④界面证据（截图或具体文字）。
最后附：改动文件清单 + selftest 输出原文 + 仍未解决项清单。
产品身份三件套（preflight 的 product_clue、probe 的 PRODUCT CLUE 行、
discover 的 product_name/install_dir）无论结论如何都必须完整回传。

## 红线（违反任意一条立即停下回报）

- **不冒充验证**：不许拿 ArcGIS Pro 的结论冒充 GeoScene 已验证；不许因为
  "内核相同"就跳过任何一项核验；`ArcGISProject("CURRENT")` 在 GeoScene Pro
  里不可用时，停在核验第 2 步如实回报，不许用文件回退顶替后报成实时接入成功。
- **不碰无关环境**：不要使用、安装或修改与本任务无关的既有项目环境
  （包括其他 Conda 环境）；尤其**不许往 GeoScene Pro 自带 Python 环境里
  pip 装包或改配置**，需要别的解释器跑 MCP 服务端时用系统现成的 Python 3 即可。
- **原件只读**：先用无头桥 backup，再复制出工作副本；一切写验证只在副本上做。
- **mode=file-fallback 必须如实说**，不许报成实时接入成功；拿不到进程内当前
  工程就停在核验第 2 步。无头 inspect 的结果必须标注"已保存状态"，不许说成实时。
- **写操作先确认**：add_layer_from_path、save_project 的 confirm=true 只能在
  用户明确同意后由你填入，不许自作主张绕过闸口。
- 许可/版本报错即停，回报原始报错全文，不许换版本、换环境反复试探。
- 不许自行扩展工具集或动作范围；**尤其不许临时加任意代码执行或任意 GP
  调用工具来"凑"核验结论**。发现 API 与脚本假设不符，回报现场方法清单，
  等维护者据实收紧，不要在实机临时发明新策略后当成定案。

## 从 SuperMap 实机校准迁移的通用教训（2026-10-24）

SuperMap 桥已于 2026-10-24 在 iDesktop 10i 上完成第一轮实机校准
（结论见同合集仓 `supermap/docs/CALIBRATION-RESULTS-20261024.md`）。
其中跨软件通用的教训已按本包形态迁移；**迁移的只是纪律与代码写法，
不是 GeoScene Pro 的实机结论**——本包与 GeoScene Pro 的兼容性仍是
同源推断，未经任何实机验证，本节不改变文首的核验定位。

### 已落到本包代码 / 文档（v0.2）

- **selftest 线程读**：`live/selftest.py` 读取子进程 stdout 改为后台线程 +
  队列（`_LineReader`），删除 `select` 实现。SuperMap 实测：Windows 上
  `select()` 对管道句柄抛 WinError 10038，此写法跨平台一致。
- **token 文件环境变量**：token 文件位置可用 `GEOSCENE_BRIDGE_TOKEN_FILE`
  覆盖（`live/inapp_bridge.py`、`live/mcp_server.py`、`live/selftest.py`
  三处一致），应对受控文件夹访问等导致默认用户目录不可写的环境。
- **verify 脚本**：新增 `scripts/verify_project.py`——只读盘点工程
  （纯标准库层查文件 / ZIP 结构 / shapefile 伴生完整性，arcpy 层枚举
  地图 / 图层 / 表 / 布局，并回报 product_clue），`--copy-to` 整包复制后
  对副本重开盘点做迁移验收；无 arcpy 时结构化报错
  `ARCPY_NOT_AVAILABLE` 并退出码 1，不抛 traceback。
  配套纪律见 `ENGINEERING-PLAYBOOK.md`。
- **原件纪律与证据口径**：先备份、只改副本、原件 mtime 验收、写后重读
  验证、导出以真实落盘为准——已写入 `ENGINEERING-PLAYBOOK.md`。

### 仍是待本软件实机验证的假设（不要当作已验证结论）

- **兼容性本身**：`arcpy.mp.ArcGISProject("CURRENT")` 等接口在 GeoScene Pro
  中的可用性仍是本指南对照表第 0–1 项要证实或证伪的前提，SuperMap 的
  任何结论都不能替代这一步。
- **写回持久化**：CIM 定义回写（图层显隐的备用路径、标注 `showLabels`
  在 CIM 中的确切位置）改完后是否真进工程文件、保存后重开是否仍在；
  SuperMap 侧"改包装对象不回写就等于没改"与"旧专题路径假成功"两条
  实测教训在本包只是风险提示，且其在 GeoScene 的对应形态完全未知。
- **导出参数**：`Layout.exportToPNG` 的分辨率参数位置、
  `MapFrame.exportToPNG` 的存在性与宽高参数在 GeoScene Pro 中是否与
  ArcGIS Pro 一致，仍是待核验假设。
- **假成功路径**：`Map.addDataFromPath` 调用不报错但图层未落位、
  `layers_after` 计数不可信等情形是否存在，须以界面与重开盘点双重
  证据判定，不能只看桥的回报 JSON，更不能以 ArcGIS Pro 上的表现推断。
