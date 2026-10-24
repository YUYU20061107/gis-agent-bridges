# ROADMAP —— geoscene-bridge 演进与兼容性核验清单

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | 由 Pro 版同包逐文件衍生：无头桥三件只读动作：preflight（多策略定位 GeoScene Pro 自带 Python + arcpy/许可预检 + 产品身份线索 product_clue）、backup（时间戳备份 + sha256，同名 .gdb 整体复制）、inspect（复制到临时目录后盘点，固定标注 headless-saved-state）；兼容性探针 probe_api.py；实时桥（Blender MCP 模式）：inapp_bridge.py 跑在 GeoScene Pro 的 Python 窗口/Notebook 内（127.0.0.1:47619 + token 鉴权 + 当前工程多策略发现），mcp_server.py 纯标准库 stdio 转发；12 个工程工具 + ping（只读 7、视图级 3、写类 2 个带 confirm 闸、导出 1） | VM 侧已验证：全部脚本语法、selftest 6/6 PASS、无 arcpy 环境下 preflight/inspect 的结构化报错与退出码、backup 真复制 + sha256 + .gdb 整体复制；**与 GeoScene Pro 的兼容性（CURRENT 可用性、产品身份确认、各 API 形态）全部未实机验证**，按 docs/CALIBRATION.md 的对照表在实机逐项核验——这是先于一切功能演进的第一里程碑 |
| v0.2 | 协议层与工程纪律升级（自 SuperMap 2026-10-24 实机校准迁移通用教训）：live/selftest.py 改 _LineReader 后台线程 + 队列读行、删 select 实现；token 文件支持 GEOSCENE_BRIDGE_TOKEN_FILE（inapp_bridge / mcp_server / selftest 三处一致）；serverInfo 与 ping 版本升 0.2；新增 scripts/verify_project.py（只读盘点 + --copy-to 迁移验收，含 product_clue）与 ENGINEERING-PLAYBOOK.md；docs/CALIBRATION.md 增补迁移教训一节 | VM 侧验证已于 2026-10-24 总复核记录（py_compile 全过、selftest 6/6 PASS、verify 无库结构化报错符合预期）；**与 GeoScene Pro 的兼容性仍全部未实机验证**，核验清单不变，仍是第一里程碑 |

## 待实机核验清单（按依赖顺序，与 docs/CALIBRATION.md 对照表同序）

0. **产品身份确认**（本包特有前置项）：preflight 的 product_clue、probe 的
   PRODUCT CLUE 行、discover 的 product_name/install_dir 三处原文互相印证，
   确认当前 arcpy 属于 GeoScene 而非同机共存的 Esri ArcGIS。此项不过，其余暂停。

1. **discover 钉死实时工程策略**：GeoScene Pro 的 Python 窗口与 Notebook 两种会话里
   `ArcGISProject("CURRENT")` 是否都可用、返回的是否就是 GUI 里打开的那个工程
   （mode 必须为 `live:CURRENT` 或 `live:global:*`，用 list_maps / list_layers 与界面逐项对）。
   file-fallback 不算数。另记录桥的后台线程调用 arcpy.mp 是否出现线程相关异常。
2. **preflight/inspect 实机口径**：preflight 回报的 Version/LicenseLevel 与
   帮助→关于 一致；inspect 对一份已知工程的盘点（地图/图层/表/布局、断裂图层标记）
   与 GeoScene Pro 里已保存状态逐项对上；重点核对组图层、独立表、相对路径数据源的报告是否属实。
3. **set_layer_visible / set_labels_visible**：visible / showLabels 属性赋值是否即时
   反映到界面；属性途径失败时 CIM 回写（getDefinition 的版本字符串 V2/V3、
   showLabels 在 CIM 中的确切位置）哪条能命中，把命中结果回写代码并注明版本。
4. **zoom_to_layer**：activeView 在地图视图/布局视图/无视图三种状态下的可用性；
   camera.setExtent 与 camera.extent 赋值哪条命中；Describe(layer).extent 对
   栅格、注记、组图层等类型的可得性边界。
5. **export_map_image**：Layout.exportToPNG 的真实签名（分辨率参数位置）；
   MapFrame.exportToPNG 的存在性与宽高参数；导出内容与界面一致性（以落盘+字节>0+能打开为准）。
6. **add_layer_from_path**：Map.addDataFromPath 对 shp / gdb 要素类 / 栅格 / .lyrx 的
   返回对象与图层落位（顶部还是底部）；layers_after 计数是否可信，不可信时以界面为准的口径回写文档。
7. **save_project**：仅在副本上、经用户当场确认后验；保存后重开副本核对改动在；
   file-fallback 模式下 save 的目标文件与界面工程不是同一个时，回报口径是否足够醒目。
8. 每个工具的命中策略（via）回写收紧：把多策略顺序按实机结果排序或删减，并在对应工具
   docstring 里注明实机版本（GeoScene Pro 具体版本 + arcpy 版本）。

## 后续候选（桌面评估结论，均未实机验证）

- **GP 工具白名单执行**：同类项目已有"GP 白名单/黑名单"做法。若未来确有需求，
  只考虑**白名单制**：单个具名 GP 工具 + 参数留档 + confirm 闸 + 结果回读，
  逐个评审加入；**任意代码执行（execute_python 类）不在本项目路线图上**，
  这是与项目定位绑定的红线，不是待补功能。
- **与 Pro 版的同步策略**：本包与 Pro 版共享行为逻辑。Pro 版在 ArcGIS Pro
  上取得的校准结论**只能作为 GeoScene 核验的假设清单，不能直接迁移为
  GeoScene 的结论**；每项都要在 GeoScene Pro 上独立复验后才许写进本包的
  已验证口径。反之，本包核验中发现的内核层差异（如 CIM 字段位置不同），
  应回馈 Pro 版一并评估。
- **核验通过后的演进**：兼容性对照表全项有结论（通过或明确不通过并记录）
  之后，本包才进入与 Pro 版相同的功能演进节奏；在此之前不新增工具、
  不扩大动作面。
