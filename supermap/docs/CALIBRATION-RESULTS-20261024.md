# 实机校准结果（2026-10-24，iDesktop 10i / 文件回退模式）

本文件记录 supermap-gis-bridge v0.3 的第一轮实机校准结论：验证环境、逐项结论、
与 v0.3 原包的差异、实测钉死的 API 事实与运行时搭建方法。校准顺序与纪律见各包
的校准工单；iDesktopX 实时模式的校准尚未进行，不在本文件范围内。

## 1. 验证环境

| 项 | 值 |
|---|---|
| 产品 | SuperMap iDesktop 10i(2020)，版本 10.1.0 |
| iObjects Java | 10.1.0.19113（BuildNum 83124，取自 `Bin\com.supermap.data.jar` 的 Manifest） |
| iobjectspy | 10.1.0.0（PyPI sdist，py35_64 分支） |
| Python | 3.5.4（iDesktop 自带运行时独立复制使用，不改 SuperMap 安装） |
| Java 运行时 | OpenJDK 1.8.0_232（iDesktop 自带） |
| 许可 | Sentinel LDK 许可服务在运行；构造 `Workspace()` 的许可冒烟 ok |
| 缺失 | 无 iDesktopX；无独立的 iObjects Java `Bin_x64`（以 iDesktop 的 `Bin` 代用，够用） |

## 2. 结论边界（先读这一段）

- 校准环境**没有 iDesktopX**，拿不到 GUI 里的实时对象。实时桥在本环境只能跑
  `mode=file-fallback`：在带时间戳的**工作空间副本**上操作，**界面不会刷新**。
  任何回报都必须如实标注 `mode=file-fallback`，不许说成实时接入。
- iDesktopX 的 `live:*` 实时策略仍未验证，待有 X 的环境时按校准工单继续。
- 本文件结论只对上表环境成立（iDesktop 10i 10.1.0 + iobjectspy 10.1.0.0）；
  其他版本组合需重新校准。

## 3. 验证清单（13/13 工具 + 无头三件套）

无头桥（`scripts/supermap_bridge.py`）：

| 动作 | 结论 | 证据摘要 |
|---|---|---|
| preflight | 通过 | 许可冒烟 ok，版本回报与环境一致 |
| backup | 通过 | 生成带时间戳副本并回报 sha256 |
| inspect | 通过 | 真实数据源/数据集/记录数/地图盘点出数；连带复制相对路径数据源后不再误报为空 |

实时桥（file-fallback，经 `live/run_bridge_copy.py` 在副本上起桥）：

| 工具 | 结论 | 证据摘要 |
|---|---|---|
| supermap_ping | 可用 | 回报 pong 与桥侧 Python 版本（3.5.4） |
| supermap_discover | 可用 | `mode=file-fallback`，现场 API 方法清单原样回传 |
| supermap_workspace_info | 可用 | 副本概览：1 个数据源 / 2 张地图 |
| supermap_list_datasources | 可用 | 数据源别名与引擎（UDBX）回报正确 |
| supermap_list_datasets | 可用 | 4 个数据集（POINT / LINE） |
| supermap_list_maps | 可用 | 2 张地图名回报正确 |
| supermap_list_layers | 可用 | 图层 caption + 显隐状态；写操作后能立即复核到变化 |
| supermap_export_map_image | 可用 | 1200×900 PNG 真实落盘（含标签专题标注） |
| supermap_set_layer_visible | 可用 | 显隐与设置一致、`committed=true`，导出图确实随之变化 |
| supermap_zoom_to_dataset | 可用 | 视野缩放到数据集范围并回报视野矩形 |
| supermap_add_dataset_to_map | 可用 | `confirm=true`：图层 1→2、`committed=true`，随后 list_layers 复核到 2 层 |
| supermap_make_label_thematic | 可用 | `confirm=true`：走 `add_dataset(layer_setting=ThemeLabel)`；重开副本专题仍在，导出图出现字段标注 |
| supermap_save_workspace | 可用 | `confirm=true`：`saved=true`；重开副本为改动后状态且专题还在，**原件 mtime 全程未变** |

写类三项均只在**副本**上以 `confirm=true` 验证：改动持久（保存后重开副本仍在），
原件全程只读。协议层自检 `live/selftest.py` 在 Windows 下 6/6 PASS（原实现用的
`select()` 等管道句柄在 Windows 上不可用，已改后台线程 + 队列逐行读取）。

## 4. 实测钉死的 API 事实

1. **打开工作空间必须接住返回值**：iobjectspy 10.1 的打开方式是
   `ws = ws.open(WorkspaceConnectionInfo(path))`，`open()` 返回新对象，旧句柄随即
   disposed，不接返回值后续操作全部落空。
2. **写操作必须 `set_map` 回写**：`get_map/get_maps` 每次返回新的 Map 包装对象，
   只在包装对象上改图层，后续请求与 `save()` 都看不到；必须
   `ws.set_map(name, map)` 回写，保存才落盘（桥内 `_commit_map` 助手）。
3. **旧专题路径是假成功**：给已有图层设置专题的旧路径只改 Python 包装对象，
   既不渲染也不进工作空间 XML（改前改后导出图 sha256 相同可复现）。唯一可靠
   入口是 `Map.add_dataset(dataset, layer_setting=ThemeLabel(...))` 新建专题图层，
   再 `set_map` 回写。
4. **导出尺寸用关键字**：`Map.output_to_file(file_name, image_size=(w, h))`；
   尺寸作位置参数传元组会被当成 `output_bounds` 而报错。
5. **inspect 必须连带复制相对路径数据源**：工作空间里的数据源常为相对路径，
   只复制 `.smwu` 到临时目录会让数据源连不上、盘点误报“数据集为空”；须把同目录
   （含一级子目录）的 `.udb/.udbx/.udd` 一起复制。
6. **Windows 下 selftest 不能用 `select()` 等管道**：`select()` 对管道句柄抛
   WinError 10038；跨平台写法是后台线程读 stdout + 队列逐行取。
7. **桥必须容忍只读 CWD**：iobjectspy 会往当前工作目录写 `iobjectspy.log`，
   CWD 只读时工作空间直接打不开；桥启动时探测 CWD 可写性、不可写则切到临时
   目录，副本启动器建好副本后 `chdir` 到副本目录。

另确认：数据源引擎类型在 `ds.connection_info.type` 上（如 `EngineType.UDBX`），
不在数据源对象本身；地图集合走 `ws.get_maps()` 返回 `list[Map]`。

## 5. 与 v0.3 原包的差异（逐文件）

| 文件 | 改动 |
|---|---|
| `scripts/supermap_bridge.py` | ① 打开策略：`WorkspaceConnectionInfo(path)` + 接住 `ws.open()` 返回值；② 引擎类型改从 `ds.connection_info.type` 取；③ 子命令必填校验改手动判断，兼容 Python 3.5；④ inspect 连带复制同目录（含一级子目录）的 `.udb/.udbx/.udd` |
| `live/inapp_bridge.py` | ① 同上打开策略（file-fallback）；② 引擎字段同上；③ 新增 `_commit_map()`：`ws.set_map(name, map)` 回写；④ 图层显隐/加图层后回写；⑤ 标签专题改走 `Map.add_dataset(dataset, layer_setting=ThemeLabel)`；⑥ 导出使用 `output_to_file(..., image_size=(w,h))` 关键字签名；⑦ 启动时探测 CWD 可写性，不可写切临时目录；⑧ token 支持 `SM_BRIDGE_TOKEN` / `SM_BRIDGE_TOKEN_FILE` 环境变量 |
| `live/mcp_server.py` | ① token 文件支持 `SM_BRIDGE_TOKEN_FILE`；② 新增用时自动启动：桥端口不通且配置了 `SM_BRIDGE_AUTOSTART*` 时，经 `run_bridge_copy.py` 在**副本**上拉起桥并等待就绪（`SM_BRIDGE_AUTOSTART_PYTHON` 未配置则不启动并打日志）；③ 自动启动子进程显式带 `cwd` 与日志重定向；④ 自动启动失败返回明确错误 |
| `live/selftest.py` | Windows 修复：`select()` 不能等管道句柄（WinError 10038），改为后台线程 + 队列逐行读取 |
| `live/run_bridge_copy.py`（新增） | 在**工作空间副本**上启动桥：复制 `.smwu` 与同级/一级子目录数据源、`chdir` 到副本、端口占用时友好退出 |
| `live/start_bridge.cmd`（新增） | 拖拽式启动器：把 `.smwu` 拖到脚本上即可在副本上起桥；解释器/token/工作目录走环境变量或 `%USERPROFILE%\.supermap-live-bridge` 中性默认，安装路径按本机修改 |
| `SKILL.md` | 加 YAML frontmatter 与「实机验证状态」引用块（本文件为其详细版） |

## 6. 运行时搭建（复现校准环境）

校准用的专用运行时不改 SuperMap 安装，步骤如下（路径均为占位符）：

1. 复制 `<iDesktop 安装目录>\Tools\Python` 到独立目录（如 `<sm35-runtime>`）。
2. 把 iobjectspy 10.1.0.0 sdist 里与解释器小版本匹配的分支（Python 3.5.3+ 用
   `iobjectspy-py35_64`，3.5.2 及以下用 `iobjectspy-py352_64`）中的 `iobjectspy`
   包放进 `<sm35-runtime>\Lib\site-packages`。
3. 把 `py4j 0.10.7` 放进同一 `site-packages`。
4. 在 `Lib\site-packages\sitecustomize.py` 里把 `<iDesktop 安装目录>\Bin` 与
   `<iDesktop 安装目录>\Tools\jre\bin` 插到 PATH 最前（原生库与 Java 运行时靠它定位）。
5. 调一次 `iobjectspy.set_iobjects_java_path(r"<iDesktop 安装目录>\Bin")`，
   让其 `env.json` 指向 iDesktop 的 iObjects Java 组件（会把所需 jar 复制进
   iobjectspy 的 `_jsuperpy/jars`）。

之后用 `<sm35-runtime>\python.exe` 跑无头桥脚本，或经 `live/start_bridge.cmd` /
`live/run_bridge_copy.py` 在副本上起实时桥。

## 7. 已知限制（如实记录）

- 无 iDesktopX → 没有 `live:*` 实时对象；一切实时桥结果都是 file-fallback，
  操作的是带时间戳的工作空间副本，界面不会刷新。
- 每次启动有 `WrapjMObjects.dll: Can't find dependent libraries` 告警
  （MObjects/3D 相关，被捕获，不影响矢量与地图功能）与 SLF4J NOP 提示。
- 校准环境导出的 PNG 带 "SuperMap Personal use only" 水印（该环境许可属性）。
- 自动启动的桥看到的是**拉起那一刻的快照**；在 iDesktop 里改过工作空间后，
  需结束桥进程再重新调用，才能看到新内容。
- 校准包不含 Python 运行时、iobjectspy 组件与任何工作空间数据（体积/许可原因），
  按第 6 节自行搭建。

## 8. v0.4 工程文件生产增补（2026-10-24）

在第 1 轮校准基线上增补工程文件生产资产（桥的对外动作不变）：

- `ENGINEERING-PLAYBOOK.md`：工程文件生产手册（进程与单 Workspace 纪律、复制优先、
  CRS、地图副本与 set_map 回写、字段保留字、轨迹点线、交付校验清单、症状速查）。
- `SCENE-AND-GUI.md`：三维场景与 GUI 保存（无头能力边界、场景 XML 结构、
  ECEF→SuperMap 相机换算、GUI 两步保存、排错）。
- `templates/scene_globe_template.xml` + `templates/NOTICE.md`：三维球面场景 XML
  模板（来源与许可说明见 NOTICE）。
- `scripts/make_scene_xml.py`：由命令行参数或 JSON 规格生成场景 XML
  （纯标准库，不改工作空间）。
- `scripts/add_scene_xml.py`：把场景 XML 注入工作空间副本
  （`--confirm` 闸、默认备份、同名默认拒绝）。
- `scripts/verify_workspace.py`：工作空间盘点/换目录迁移验收（只读）。
- `live/selftest.py`：支持 `SM_BRIDGE_TOKEN_FILE` 环境变量指定 token 文件位置
  （应对受控文件夹访问等导致默认用户目录不可写的环境）。

验证分工（如实标注）：

- **工程方自报**（本机 iDesktop 10i 实机）：副本注入场景 before=1 → after=2、
  备份文件生成、重开可见；`verify_workspace.py` 对含场景副本输出 issues 为空、
  CRS 显示 GCS_WGS_1984 (4326)；对 Result 做 `--copy-to` 迁移验收：5 个数据集、
  地图 5 层、范围 118.8925–118.9144, 32.0976–32.1222；`SM_BRIDGE_TOKEN_FILE`
  指向工作区时 selftest 6/6 PASS。
- **文件级/VM 复核**（Muse 侧）：新增与修改的全部 Python 文件 py_compile 通过；
  `make_scene_xml.py` 以样例规格生成场景 XML 成功（图层替换与相机四元数输出
  正常）；`live/selftest.py` 在 VM 复跑 6/6 PASS。实机行为以工程方自报为准，
  未在 Muse 侧实机复跑。
