# 实时桥使用说明（GeoScene Pro 应用内桥 + MCP 接入，v0.1）

架构（同 Blender MCP 的模式）：
GeoScene Pro 进程内跑一个桥脚本（拿到当前打开的工程）→ 本机 127.0.0.1:47619 →
MCP 服务端（stdio）→ 你的 AI Agent 调用工具直接操作你正开着的工程，界面实时可见。

## 启动三步

1. 打开 GeoScene Pro，打开要操作的工程，并打开至少一个地图视图。
2. 在 GeoScene Pro 里打开 Python 窗口或 Notebook，运行应用内桥：
   - 在 Python 窗口里执行：
     `exec(open(r"<包路径>\live\inapp_bridge.py", encoding="utf-8").read())`
   - 看到 `[geoscene-live-bridge] listening on 127.0.0.1:47619` 即桥已上线；
     它同时把本次 token 写到 `~/.geoscene-live-bridge.token`，MCP 服务端自动读取，无需手填。
   - Notebook 里同样 exec 本文件即可（预期 Notebook 内核运行在 GeoScene Pro
     进程内、`ArcGISProject("CURRENT")` 可用——这正是兼容性核验第 1 项要证实
     或证伪的假设，不要预先当真；若没有打开的地图视图，zoom_to_layer 会如实报错）。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端（命令与参数按该客户端的配置格式填）：
   - command: 任意 Python 3 解释器（不需要装 arcpy，它只做转发）
   - args: `<包路径>\live\mcp_server.py`
   注册后客户端应能列出 13 个 geoscene_* 工具（12 个工程工具 + 1 个连通性 ping）。

接入前可先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token 共 6 项，
全 PASS 才说明包本身没坏；它不验证与 GeoScene Pro 的对接，更不构成兼容性证明）。

## 工具清单（v0.1，共 13 个：12 个工程工具 + ping）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；视图级＝只改
显示状态、可逆、不落盘；写类＝改变工程内容，全部带 confirm=true 闸
（confirm 只能在用户明确同意后由 Agent 填入）。

| 工具 | 作用 | 风险 |
|---|---|---|
| geoscene_ping | 桥是否在线 | 只读 |
| geoscene_discover | 发现当前工程接入方式 + 现场 API 清单（校准用） | 只读 |
| geoscene_project_info | 当前工程概览（路径/默认地理数据库/地图数/布局数/接入模式） | 只读 |
| geoscene_list_maps | 列地图（名称、类型） | 只读 |
| geoscene_list_layers | 列某地图的图层（下标/名称/显隐/数据源/是否断裂） | 只读 |
| geoscene_list_tables | 列某地图的独立表（名称、数据源、是否断裂） | 只读 |
| geoscene_list_layouts | 列布局（名称、页面宽高、地图框数） | 只读 |
| geoscene_export_map_image | 导出布局/地图框为 PNG 到指定路径（以文件真落盘为准） | 只读出文件 |
| geoscene_set_layer_visible | 设置图层显隐 | 视图级 |
| geoscene_zoom_to_layer | 活动视图缩放到图层范围 | 视图级 |
| geoscene_set_labels_visible | 开关图层标注显示 | 视图级 |
| geoscene_add_layer_from_path | 把数据路径加入地图（须 confirm=true） | **写** |
| geoscene_save_project | 保存当前工程（须 confirm=true） | **写** |

工具面是**刻意收窄**的：没有任意代码执行、没有任意 GP 工具调用。
Agent 能做的事被限定在这份可枚举、可审计的清单内，这是本项目有意的安全取舍，
不是功能缺失；需要清单之外的能力时，停下来回报，不要绕过桥自行其是。

v0.1 的全部实时工具为**实验性实现，未在真实 GeoScene Pro 上验证**，且其与
ArcGIS Pro 的 API 兼容这一前提本身也是待核验项：当前工程发现、
活动视图相机、图层 CIM 定义、布局导出等 API 的真实形态因 Pro 版本而异，桥用
多策略尝试并在结果里回报命中的策略（via）；拿不到对象或 API 不匹配时返回结构化
错误（NOT_SUPPORTED / *_FAILED，附现场方法清单线索），这属于预期行为，
Agent 必须如实回报，不许粉饰成成功。首次实机校准按 `docs/CALIBRATION.md`
的顺序逐项进行（先 discover 钉死策略，写类工具只在工程副本上验）。

## 纪律

- 桥只监听 127.0.0.1 且带 token，不要改成对外监听，不要把 token 发给任何人。
- discover 的结果是判断"接入是否真的是 GUI 里那个工程"的依据：
  若 mode 显示 file-fallback，说明走的是文件回退（只能看到存盘状态），
  操作不会实时反映到界面，必须如实回报用户，不许说成实时接入。
- 写类工具的 confirm=true 只能在用户明确同意后由 Agent 填入，不许自作主张绕过。
- 桥在后台线程里调用 arcpy.mp；若实机出现线程相关异常或 GeoScene Pro 界面卡死，
  先停下，按 docs/CALIBRATION.md 记录现象回报，不要反复重试。
- GeoScene Pro 里若弹出未保存提示等 GUI 阻塞，工具会超时——先处理弹窗再重试，不要连环重试。

## 首次校准工单（给执行校准的 AI Agent，可直接粘贴）

> 按 `<包路径>\live\LIVE.md` 启动实时桥并完成兼容性核验。目标结果：(1) geoscene_ping 通；
> (2) geoscene_discover 完整回报（mode、attempts、mp_class_methods、main_globals、
> product_name、install_dir 原样回传）——先据 product_name/install_dir 确认接的
> 是 GeoScene 的 arcpy，身份不对就停；
> (3) geoscene_list_maps、geoscene_list_layers、geoscene_list_layouts 的结果与
> GeoScene Pro 界面里看到的一致，并截图或文字确认界面里打开的正是同一个工程。
> mode 若为 file-fallback 就直说，不许报成实时接入成功。
> 全程除非我点名，不许调用任何写类工具（add_layer_from_path、save_project）。
> 后续逐项校准操作工具时改按 docs/CALIBRATION.md 执行。
