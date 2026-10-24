# arcmap-bridge-lite

> **English** — arcmap-bridge-lite is a small, personal-use bridge that lets an
> AI agent inspect and operate ArcMap map documents (.mxd) through Esri's
> official Python package (arcpy.mapping): a *headless bridge* that inventories
> and backs up .mxd files against copies only, and a *live MCP bridge* that
> runs inside ArcMap's own Python window so any MCP client can read and
> operate the document you currently have open.

让 AI Agent 通过 Esri 官方 Python 包 **arcpy.mapping** 操作 ArcMap 地图文档
（*.mxd）的轻量受控桥接工具，而不是让 Agent 直接读写二进制文件。
所有动作都是有限、受控、带安全闸的；动作之外不许 Agent 自行发挥。

## 诚实定位声明（请先读这一段）

- **ArcMap 已被 Esri 退役**：ArcMap 处于最终支持阶段，**2026 年 3 月 1 日
  正式退役，10.8.2 为最终版本**，官方建议迁移到 ArcGIS Pro。
  因此本包**定位为个人自用工具**：给手头还在用 ArcMap 的人一个小而稳的
  Agent 接入，不做系列门面，不承诺长期演进。
- **无头模式只能读已保存状态**：在 ArcMap 之外用文件路径打开 .mxd，
  看到的是磁盘上已保存的内容，看不到 GUI 里尚未保存的修改。inspect 的
  输出会标注 `mode=headless-saved-state`，不冒充实时。真正的实时只有
  应用内桥（在 ArcMap Python 窗口内经 `MapDocument("CURRENT")` 接入）一条路。
- **运行时是 Python 2.7**：ArcMap Desktop 10.x 自带的解释器是 Python 2.7
  （如 `C:\Python27\ArcGIS10.x\python.exe`）。桥侧与无头脚本都写在
  Python 2.7 / 3.x 兼容子集上；MCP 服务端跑在进程外，用任意 Python 3。
- **v0.2（2026-10-24）**：selftest 改后台线程 + 队列读行（修 Windows
  select 等管道句柄问题）；token 文件位置可用环境变量
  ARCMAP_BRIDGE_TOKEN_FILE 覆盖；新增只读盘点/迁移验收脚本
  scripts/verify_project.py 与 ENGINEERING-PLAYBOOK.md；工具清单、
  端口与安全闸不变，仍未实机验证（迁移说明见 docs/CALIBRATION.md）。
- **v0.3（2026-10-25）**：由 lab2 实机魔改版回灌——修复 py2 下 emit()
  含中文崩溃与 sys.argv GBK 路径乱码两个实机坑（并同步到
  verify_project.py / probe_api.py / inapp_bridge.py）；无头桥新增三个
  受控写动作（georef / mkvector / buildmxd，均须 --confirm-write、
  禁覆盖原件）；serverInfo 升 0.3.0。
- **实机校准状态（2026-10-25）**：无头桥已在 ArcGIS Desktop 10.8 /
  Python 2.7.16 实机跑通（含三个受控写动作），详见
  [docs/CALIBRATION.md](docs/CALIBRATION.md) 的校准记录；**实时桥仍未
  在真实 ArcMap 窗口内校准**，其 2.7 窗口内行为仍属未知，勿冒充已验。

## 两种模式

### 无头桥（headless）

外部脚本操作 .mxd 文件。三件只读动作 + 三件受控写动作（写动作须 --confirm-write、只写新路径、与源同目录时拒绝执行）：

| 动作 | 说明 |
|---|---|
| `preflight` | 环境预检：多策略定位 Desktop 的 Python/arcpy，回报候选路径与版本 |
| `backup` | 给 .mxd 生成带时间戳的备份副本并回报 sha256；同名 .gdb 文件夹一并整体复制 |
| `inspect` | 工程盘点：先复制到临时目录再打开（原件零接触），输出数据框/图层/表视图 JSON，标注 headless-saved-state |
| `georef` | 一次多项式（仿射）配准：控制点解系数/残差 + world file，可选重采样纠正（受控写） |
| `mkvector` | 按 JSON 规格生成 shapefile，回报写入数/计数双校验（受控写） |
| `buildmxd` | 套模板组装 .mxd（先 saveACopy 再改），可选导出布局图（受控写） |

另有校准探针 `scripts/probe_api.py`：首次部署或版本变更时运行一次，
输出本机 arcpy 版本、`arcpy.mapping` 关键函数清单，以及
`MapDocument("CURRENT")` 在当前进程是否可用。操作手册见 `SKILL.md`。

### 实时桥（live）

Blender MCP 式接入：桥脚本跑在 **ArcMap 进程内的 Python 窗口**里
（`execfile` 注入，后台线程开服务），拿到当前打开的地图文档；你的
AI Agent / MCP 客户端经一个纯标准库的 stdio MCP 服务端（Python 3）调用
工具，操作实时反映在 ArcMap 界面里。使用说明见 `live/LIVE.md`，
自检脚本 `live/selftest.py`。

## 架构

```
┌──────────────────────────── ArcMap 进程 ───────────────────────────────┐
│  Python 窗口 execfile live/inapp_bridge.py（Python 2.7）                │
│  → MapDocument("CURRENT") 拿当前文档 → TCP 127.0.0.1:47617（token）    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ 行分隔 JSON（请求须带 token）
┌──────────────────────────────────▼─────────────────────────────────────┐
│  live/mcp_server.py（纯 Python 3 标准库，stdio MCP 服务端）               │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ MCP (stdio)
┌──────────────────────────────────▼─────────────────────────────────────┐
│  你的 AI Agent / MCP 客户端（10 个 arcmap_* 工具）                       │
└────────────────────────────────────────────────────────────────────────┘

无头桥：Agent → scripts/arcmap_bridge.py（子命令）→ arcpy.mapping → .mxd 副本
```

（端口与同系列其他桥错开：SuperMap 47615、ArcGIS Pro 47616、本包 47617，
三个桥可以同时挂。）

## 快速上手

### 无头桥

务必用 **ArcMap Desktop 自带的 Python 2.7** 跑无头脚本（普通 Python 3
里没有 arcpy，脚本只会如实回报 `ARCPY_NOT_AVAILABLE` 并附候选路径）：

```
"C:\Python27\ArcGIS10.x\python.exe" scripts\arcmap_bridge.py preflight
"C:\Python27\ArcGIS10.x\python.exe" scripts\arcmap_bridge.py backup <你的 .mxd>
"C:\Python27\ArcGIS10.x\python.exe" scripts\arcmap_bridge.py inspect <你的 .mxd>
```

第一份任务可以这样下达给你的 AI Agent（结果式表述）：

> 读 `<包路径>/SKILL.md` 并严格按它执行。目标结果：
> (1) 用 Desktop 自带 Python 完成 preflight，回报 JSON 原文；
> (2) 运行 probe_api.py 并完整回传输出；
> (3) 对地图文档 `<你的某个 .mxd 路径>` 先 backup 再 inspect，回报两份 JSON 原文。
> 全程对原件零写入；版本/许可报错即停并回报原文，不许换环境反复试探。

### 实时桥

1. 打开 ArcMap，打开要操作的地图文档。
2. 打开 ArcMap 的 Python 窗口（Geoprocessing 菜单 → Python），执行：
   `execfile(r"<包路径>\live\inapp_bridge.py")`
   看到 `[arcmap-live-bridge] listening on 127.0.0.1:47617` 即桥已上线；
   本次 token 写到 `~/.arcmap-live-bridge.token`，MCP 服务端自动读取。
   （py2 的 Python 窗口里 `open(..., encoding=...)` 不可用，所以用
   `execfile`；若你的控制台是 Python 3 风格，也可以用
   `exec(open(r"<路径>", encoding="utf-8").read())`。）
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端：
   - command：任意 Python 3 解释器（不需要 arcpy，它只做转发）
   - args：`<包路径>\live\mcp_server.py`
   注册后客户端应能列出 10 个 arcmap_* 工具。

接入前建议先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层。

## 工具清单

### 实时桥（10 个工具）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；
视图级＝只改显示状态、可逆、不落盘；写类＝改变文档内容，带 confirm=true 闸
（confirm 只能在用户明确同意后由 Agent 填入）。

| 工具 | 作用 | 风险 |
|---|---|---|
| arcmap_ping | 桥是否在线 | 只读 |
| arcmap_discover | 发现当前文档接入方式 + 现场 API 清单（校准用） | 只读 |
| arcmap_document_info | 当前文档概览（路径/活动视图/页面大小/数据框与图层数） | 只读 |
| arcmap_list_dataframes | 列数据框（名称、范围、比例尺、空间参考） | 只读 |
| arcmap_list_layers | 列图层（可按数据框过滤；名称/数据源/显隐/断裂） | 只读 |
| arcmap_list_tables | 列独立表视图（名称、数据源） | 只读 |
| arcmap_export_map_image | 导出当前文档为 PNG 到指定路径（以文件真落盘为准） | 只读出文件 |
| arcmap_set_layer_visible | 设置图层显隐（缩放后自动刷新视图） | 视图级 |
| arcmap_zoom_to_layer | 数据框视图缩放到图层范围并刷新 | 视图级 |
| arcmap_save_document | 保存当前文档（须 confirm=true） | **写** |

### 无头桥（6 个动作）

`preflight`（只读）、`backup`（只读原件，生成副本）、`inspect`（只读，
操作的是临时副本）；`georef` / `mkvector` / `buildmxd`（受控写：必须
--confirm-write，只写调用方给出的新路径，禁止覆盖原件）。

## 安全模型

- **仅本机**：实时桥只监听 127.0.0.1；每次启动生成随机 token，
  请求必须带对 token 才执行，token 经本地文件在桥与 MCP 服务端之间传递。
- **写操作 confirm 闸**：唯一的写工具 save_document 缺 `confirm=true`
  一律拒绝执行；confirm 只能在用户明确同意后填入。
- **无头模式只操作副本**：inspect 先复制到临时目录再打开；backup 只生成
  新副本、从不覆盖；任何写需求都先 backup、只改工作副本，原件零写入。
- **如实报错纪律**：调不通的工具返回结构化错误并附现场方法清单，
  配套文档明确要求 Agent 如实回报，不许把失败粉饰成成功；
  mode=file-fallback 必须如实说，不许报成实时接入成功。

## 环境要求

- ArcMap Desktop 10.x（10.8.x 为最终版）及一份你自己合法持有的许可
  （本项目不提供、不绕过任何许可机制）。
- 无头桥与应用内桥：ArcMap 自带的 Python 2.7（`C:\Python27\ArcGIS10.x`）。
- MCP 服务端与自检：任意 Python 3（纯标准库）。
- 任一支持 stdio 的 MCP 客户端 / AI Agent（实时桥）。

## 目录结构

```
arcmap-bridge-lite/
├── README.md               本文件
├── SKILL.md                无头桥操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md              版本说明、待实机校准清单
├── docs/
│   └── CALIBRATION.md      实机校准指南（顺序、验收标准、回报格式、红线）
├── ENGINEERING-PLAYBOOK.md 工程文件生产手册（副本纪律、写后重读验证、迁移验收）
├── scripts/
│   ├── arcmap_bridge.py    无头桥脚本（preflight / backup / inspect / georef / mkvector / buildmxd，单行 JSON 输出）
│   ├── verify_project.py   只读盘点/迁移验收（--copy-to 复制后对副本重开盘点）
│   └── probe_api.py        校准探针，输出本机 arcpy 版本与关键函数清单
└── live/
    ├── inapp_bridge.py     ArcMap 应用内桥（Python 2.7/3.x 子集，localhost 服务）
    ├── mcp_server.py       MCP 服务端（Python 3，stdio 转发，纯标准库）
    ├── selftest.py         实时桥一键自检（无 ArcMap 环境可跑协议层）
    └── LIVE.md             实时桥使用说明（启动、工具清单与风险等级、纪律）
```

## 免责声明

本项目是独立的第三方个人工具，与 Esri 没有任何隶属、授权或合作关系；
ArcGIS、ArcMap、ArcPy 等名称与商标归 Esri 所有，本项目仅为互操作目的
提及。使用本工具操作 ArcMap 工程，需要你自备正版 ArcMap 软件与许可，
并自行对操作结果负责。本工具按现状提供，不附带任何明示或默示担保
（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
