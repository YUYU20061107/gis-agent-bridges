# ROADMAP —— qgis-bridge 演进与待校准清单

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.2 | selftest 改后台线程 + 队列读行（修 Windows select 等管道问题）；token 文件位置支持 QGIS_BRIDGE_TOKEN_FILE 环境变量覆盖（桥/MCP/selftest 三处一致）；新增 scripts/verify_project.py 只读盘点/迁移验收（复用 qgis_bridge.py 纯 Python 解析）与 ENGINEERING-PLAYBOOK.md；serverInfo 版本升 0.2.0；工具清单（12 个）、端口 47618、confirm 闸与 BAD_TOKEN 语义不变 | VM 侧已验证：py_compile 全过、selftest 6/6 PASS、verify_project.py 对自造 .qgs 样本盘点成功且复制迁移验收可用；**与 QGIS 本体的对接仍未实机验证**，迁移口径见 docs/CALIBRATION.md 新增一节 |
| v0.1 | 无头桥三件只读动作：preflight（环境预检+可用模式回报）、backup（时间戳备份+sha256+同名数据线索提示）、inspect（双策略：纯标准库解析 .qgs/.qgz / QgsApplication 无头打开）；校准探针 probe_api.py；实时桥（Blender MCP 模式）：inapp_bridge.py 跑在 QGIS Python 控制台内（127.0.0.1:47618 + token 鉴权 + 当前工程多策略发现 + Qt 主线程调度多策略），mcp_server.py 纯标准库 stdio 转发，12 个工具（只读 6 + 出图 1 + 视图级 2 + 写/执行 3，写/执行带 confirm 闸，刻意无任意代码执行工具）；一键自检 live/selftest.py | 无头桥：VM 侧已验证语法、backup 真复制+sha256、报错 JSON 与退出码，inspect 纯解析策略已用自造 .qgs/.qgz 样本实测；实时桥：VM 侧 selftest 6/6 PASS；**与 QGIS 本体的对接全部未实机验证**，按 docs/CALIBRATION.md 在实机逐项校准 |

## 待实机校准清单（按依赖顺序）

1. **discover 钉死实时工程策略**：QGIS Python 控制台里当前工程到底经哪条路径拿到
   （注入全局变量 / qgis.utils.iface + QgsProject.instance() / 直接 instance()），
   mode 必须为 `live:*` 且与 GUI 里打开的是同一个工程（用 project_info /
   list_layers 与界面逐项对）。file-fallback 不算数。
2. **Qt 主线程调度策略**：discover 回报的 dispatch 是 `qt-main-thread` 还是
   `worker-thread`；工作线程直执 Qt 对象在目标版本上是否稳定（有无偶发崩溃），
   据实定案并把结论回写 inapp_bridge 的 docstring。
3. **图层树形态**：layerTreeRoot 的 children 遍历、分组嵌套、节点显隐 getter
   （isVisible / itemVisibilityChecked 的真实返回类型）与 list_layers 的输出
   是否和界面图层面板逐项一致。
4. **set_layer_visible / zoom_to_layer**：显隐 setter 的真实名称
   （setItemVisibilityChecked / setVisibilityChecked）；iface 的
   actionZoomToLayer 与 canvas.setExtent 哪条在目标版本可用、缩放后界面是否即时刷新。
5. **add_layer_from_path**：ogr/gdal 提供者推断对常见格式（shp/geojson/gpkg/tif/vrt）
   是否正确；QgsProject.addMapLayer 与 iface.add*Layer 的落位与图层顺序差异。
6. **run_processing**：控制台里 processing 模块的真实可用形态（import processing
   是否直接带 run）；用无害算法（如 native:buffer 输出到临时层）在工程副本上验证，
   并核对 parameters 的键名以目标版本算法帮助为准。
7. **export_map_image**：三条策略（布局 QgsLayoutExporter.exportToImage 签名与
   ImageExportSettings 字段 / 画布 saveAsImage / QgsMapRendererSequentialJob 渲染）
   各自在目标版本的可行性，以文件落盘+字节数>0 且内容正确为准。
8. **inspect 的 QgsApplication 策略**：无头打开时 prefix path 的命中情况
   （QGIS_PREFIX_PATH / 模块相对路径 / /usr）、QT_QPA_PLATFORM=offscreen 在
   Windows/macOS 上的必要性；与 parse 策略对同一工程的盘点结果逐项对账。
9. 每个工具的命中策略（via / dispatch）回写收紧：把多策略顺序按实机结果排序
   或删减，并在对应工具 docstring 里注明实机版本（QGIS 版本）。

## 后续候选（未排期）

- **处理算法清单工具**：只读枚举 Processing 算法注册表（带过滤），便于 Agent
  在 confirm 前先核对算法 id 是否存在——仍不提供任意代码执行。
- **符号/渲染只读盘点**：图层渲染器类型、分类/分级信息进 inspect 输出。
- **与系列其他桥的共享规范对齐**：gis-agent-bridges 合集内各桥的工具命名、
  confirm 闸与校准文档格式保持同构，后续版本统一收敛。
