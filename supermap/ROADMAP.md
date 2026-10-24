# ROADMAP —— supermap-gis-bridge 演进与待校准清单

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | 无头桥三件只读动作：preflight（环境/许可预检）、backup（时间戳备份+sha256）、inspect（复制到临时目录后盘点）；校准探针 probe_api.py | VM 侧已验证语法、backup 真复制+sha256、无组件环境报错 JSON 与退出码；iobjectspy 路径未实机验证 |
| v0.2 | 实时桥（Blender MCP 模式）：inapp_bridge.py 跑在 iDesktopX Python 窗口内（127.0.0.1:47615 + token 鉴权 + 工作空间多策略发现），mcp_server.py 纯标准库 stdio 转发；7 个只读/保存工具 | VM 侧端到端协议自检通过（initialize/tools/list/ping/discover/保存闸门/token）；与 iDesktopX 本体对接未实机验证 |
| v0.3 | 实时桥补 6 个工具：list_layers（只读支撑）＋ add_dataset_to_map、make_label_thematic（写类、confirm 闸）＋ set_layer_visible、zoom_to_dataset（视图级）＋ export_map_image；枚举共享逻辑收拢为 ENUM-SHARED 块（两侧逐字一致）；新增一键自检 live/selftest.py | VM 侧 selftest 6/6 PASS；**操作类工具全部未实机验证**，按 docs/CALIBRATION.md 在实机逐项校准 |
| v0.4 | 工程文件生产增补：`ENGINEERING-PLAYBOOK.md`、`SCENE-AND-GUI.md`、`templates/` 场景模板（附 NOTICE）、`scripts/` 三件（make_scene_xml / add_scene_xml / verify_workspace）；`live/selftest.py` 支持 `SM_BRIDGE_TOKEN_FILE` | 本机 iDesktop 10i 实战沉淀（工程方自报，验证记录见 `docs/CALIBRATION-RESULTS-20261024.md` 第 8 节）；不改桥的对外动作 |

## 待实机校准清单（按依赖顺序）

1. **discover 钉死实时工作空间策略**：iDesktopX Python 窗口里当前工作空间到底经哪条路径拿到
   （注入全局变量 / 模块 getter / 其他），mode 必须为 `live:*` 且与 GUI 里打开的是同一个
   工作空间（用 list_datasources / list_maps 与界面逐项对）。file-fallback 不算数。
2. **Map 打开路径**：workspace.maps 元素是 Map 对象、名字还是信息对象；构造
   `iobjectspy.mapping.Map` 后绑定 workspace 的正确写法、按名打开的方法名
   （discover 已回报 map_class_methods 供判读）。
3. **Layers 集合形态**：get_layers/layers 的返回类型、元素（图层）的 name/caption/visible
   实际访问器；list_layers 先行验证。
4. **add_dataset_to_map**：Layers.add 的真实签名（add(dataset) 还是 add(dataset, toHead)），
   加入后界面是否即时刷新、layers_after 计数是否可信。
5. **set_layer_visible / zoom_to_dataset**：显隐 setter 名；数据集 bounds 的取得方式
   （get_bounds 的返回对象与字段名）；Rectangle2D 的构造位置（iobjectspy.data 还是
   .mapping）与 set_view_bounds 的真实方法名。
6. **make_label_thematic**：ThemeLabel 类名与设置标签表达式的方法名；专题图是经
   layer.set_theme 挂到已有图层，还是 Layers.add(dataset, theme) 新建图层；
   字段名（如 NAME）的真实大小写以数据集字段为准。
7. **export_map_image**：Map 的导出方法真名与参数（路径 / 格式 / 宽高），以文件落盘+字节数>0 为准。
8. 每个工具的命中策略（via）回写收紧：把多策略顺序按实机结果排序或删减，并在对应工具
   docstring 里注明实机版本（如 iDesktopX 某版本 + iobjectspy 某版本）。

## v0.4 候选（桌面评估结论，均未实机验证）

- **经典版 iDesktop（.NET）插件路线**：经典版有桌面插件框架，可从
  `SuperMap.Desktop.Application` 拿到 `Application.Workspace`、活动地图窗体的
  MapControl.Map 等进程内对象，理论上能在插件里开同样的 localhost 服务复用 MCP 侧。
  评估结论：**可行但门槛高**——官方许可说明中「插件开发」仅高级版提供，你手头的许可（如教学版 / 试用版）
  未必包含；且需 C# 开发与部署，迭代成本明显高于 iDesktopX 的 Python 窗口路线。
  处置：仅当目标机器无法使用 iDesktopX 时才启用；iDesktopX 路线优先。
- **ArcMap 桥（arcpy）**：ArcMap 自带 Python 2.7 + arcpy 站点包，文档成熟，做
  只读盘点与出图（arcpy.mapping）技术上没有障碍，且可复用本包的 SKILL 骨架
  （环境发现 → 只读动作 → JSON 回报 → 安全纪律）。
  评估结论：**可做但只做最小版**——ArcMap 已停止演进、Python 2.7 维护成本高；
  建议范围限于 inspect 类盘点 + MXD 出图，不做实时接入。待实际需求确实需要 ArcMap
  自动化时再单独立项，本包 v0.3 不实现。
