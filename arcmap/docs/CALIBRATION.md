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

## 从 SuperMap 实机校准迁移的通用教训（2026-10-24）

SuperMap 包已在 iDesktop 10i 上完成一轮实机校准（文件回退模式 13/13
工具通过），其中一批教训是跨软件通用的。本节记录它们在本包的落地
状态；注意：迁来的只是纪律与代码形态，**不代表本包已实机校准**，
本包在真实 ArcMap 上的状态仍以本文件前文的校准目标为准。

已落到代码/文档（v0.2）：

- selftest 的管道读行：Windows 上 select() 等管道句柄会报 WinError
  10038（SuperMap 实机钉死），live/selftest.py 已改后台线程 + 队列
  逐行读取，与 SuperMap 同形态；arcmap 侧用属性赋值设 daemon 并用
  queue/Queue 兼容导入，保持 Python 2.7 / 3.x 兼容子集写法。自检
  检查项与数目不变（仍 6 项）。
- token 文件环境变量覆盖：受限环境里用户目录可能不可写，桥、MCP
  服务端、selftest 三处的 token 文件位置已统一支持环境变量
  ARCMAP_BRIDGE_TOKEN_FILE 覆盖默认路径（SuperMap 侧同理用
  SM_BRIDGE_TOKEN_FILE，且已实机验证）。
- 只读盘点与迁移验收工具：新增 scripts/verify_project.py（只读盘点
  数据框/图层/表视图 + 断裂与数据源缺失记入 issues，--copy-to 复制
  工程与伴生文件后对副本重开盘点，结构化 JSON 输出），对应
  SuperMap 的 verify_workspace.py；无 arcpy 时结构化报错
  ARCPY_NOT_AVAILABLE 并退出码 1，不裸 traceback。
- 工程纪律成文：新增 ENGINEERING-PLAYBOOK.md（原件只读/先备份只改
  副本、伴生文件完整性、相对路径风险、写后重读验证、GUI 与无头
  边界、导出注意、迁移验收、失败如实回报）。

仍是待本软件实机验证的假设（不许当结论）：

- 写回持久化：SuperMap 钉死的是「get_map 返回副本、必须 set_map
  回写才落盘」；ArcMap 侧对应问题是 mxd.save() / saveACopy() 在
  MapDocument("CURRENT") 对象上的真实持久化行为——保存后必须重开
  副本核对改动在，未核对前不许仅凭 save 未抛异常就报成功。
- 导出参数：SuperMap 钉死的是导出尺寸须用关键字 image_size= 传参；
  ArcMap 侧 ExportToPNG 的参数形态（PAGE_LAYOUT 字符串 / 数据框
  对象 / resolution 关键字哪条命中）仍是多策略假设，以文件落盘 +
  字节数与内容核对为准。
- 假成功路径：SuperMap 存在「API 不报错但改动不进文件」的旧专题
  路径（导出图哈希可复现地不变）；ArcMap 侧是否存在同类路径（如
  图层显隐只改包装对象、TOC 不刷新）未知，验收一律走「保存后重开
  盘点 + 界面证据」，不采信单次调用的返回。
- CWD 可写性：SuperMap 的 iobjectspy 会往当前工作目录写日志文件、
  CWD 只读时须切换目录；本包经审计未发现桥/MCP 往 CWD 写日志或
  临时文件的行为（日志只走 stderr/stdout，临时文件走系统临时目录），
  arcpy 本体在实机上是否往 CWD 写文件仍待观察。

## 2026-10-25 实机校准记录（第一轮：无头桥）

环境：ArcGIS Desktop 10.8（10.8.12790）、`C:\Python27\ArcGIS10.8\python.exe`
（Python 2.7.16，32-bit）、Windows；无 ArcGIS Pro。
证据等级：执行方（DSH）实机自报 + 回收代码逐行复核；本记录与
CHANGELOG-v0.3-lab2.md、SKILL.md「v0.3-lab2 增补」节交叉印证。
**本轮只覆盖无头桥；实时桥（inapp_bridge 的 CURRENT 接入、后台线程
COM 行为等）仍未实机校准，上方待校准清单继续有效。**

实机发现与处置（五条）：

1. py2 `emit()` 含中文崩溃（`json.dumps(ensure_ascii=False)` 对 UTF-8
   字节串抛 UnicodeDecodeError）→ 已修：`_to_text()` 递归转 unicode 后
   再 dumps 并写 UTF-8 字节；同一隐患已同步修 verify_project.py 与
   live/inapp_bridge.py 的响应序列化（inapp 侧为预防性修复，未实机复验）。
2. py2 `sys.argv` 为 GBK 字节串，中文路径被 arcpy 报 ERROR 000732 →
   已修：`_dec()` 逐级解码；同步修 verify_project.py 的 argv 与
   probe_api.py 的路径参数。
3. `Warp_management` 报 ERROR 000735 不可用 → georef 的重采样改走
   `ProjectRaster_management`（BILINEAR）。
4. `arcpy.Describe` 在本机大面积残缺（raster `.width/.meanCellWidth`、
   shp `.spatialReference` 均 AttributeError）→ 替代：GetRasterProperties
   取行列数、GetCount 取要素数、坐标系读 `.prj`、范围读 `.shp` 文件头。
5. 无头 `ExportToPNG` 会把 RGB 影像渲成蓝色单色调（未动过的原始 JPG
   复现，系本机 ArcMap 无头渲染问题、非数据问题）→ 成果图改自绘合成
   （PIL），不依赖 ExportToPNG 出真彩色；实时桥 export_map_image 在
   本机同样受此影响，其校准须按此预期验收。

回归基线（lab2 流水线实测）：控制点 7 个，一次多项式 RMS 2.3884 m、
max 3.6348 m，像元 0.9165×0.9235 m；矢量 5 层（Road 242 段 /
13922.5 m；Buildings 9 / 3.02 ha；GreenLand 1 / 9.30 ha；Lake 1 /
2.97 ha；Liyuan 4 / 3.90 ha），全部 `.prj` = GCS_WGS_1984，
features_written == features_counted。
