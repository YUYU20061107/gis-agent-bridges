# geoscene-bridge

> **English** — geoscene-bridge lets an AI agent operate GeoScene Pro projects
> through the arcpy site package, in two modes: a *headless bridge* that
> inventories / backs up project files by running scripts against copies only —
> its output is explicitly labelled as the project's **last-saved state**,
> never as the live GUI state — and a *live MCP bridge* that runs inside
> GeoScene Pro's own Python window (Blender-MCP style) so any MCP client can
> inspect and operate the project you currently have open, in real time.
> The tool surface is deliberately narrow (12 project tools + ping, no
> arbitrary code execution) and every content-changing tool sits behind an
> explicit confirm gate. **Important: GeoScene Pro shares the ArcPy kernel with
> ArcGIS Pro, and this package is derived from the sibling ArcGIS Pro bridge on
> that basis — but that compatibility is an inference from the vendor's own
> technical description and has NOT been verified on a real GeoScene Pro
> installation. The first job of this package is to be run against a real
> GeoScene Pro (probe + discover) to verify it — see `docs/CALIBRATION.md`.**

让 AI Agent 通过 **arcpy** 站点包操作 GeoScene Pro 工程
（工程 *.aprx、文件地理数据库 *.gdb）的受控桥接工具，而不是让 Agent 直接
读写二进制工程文件。所有动作都是有限、受控、带安全闸的；动作之外不许 Agent 自行发挥。

本包是 GIS Agent 桥合集仓 **gis-agent-bridges** 的一员（同仓另有 SuperMap、
ArcGIS Pro、ArcMap 轻量版等子包），各子包共享同一套设计纪律：只读优先、
原件零写入、写操作 confirm 闸、如实报错、实机校准留痕。

## ⚠️ 先读这一段：兼容性是推断，未经实机验证

> **本包与 GeoScene Pro 的兼容性，是基于易智瑞官方技术体系"GeoScene 与
> ArcGIS 共用 ArcPy 内核"的表述所作的推断，不是实测结论。**
> `arcpy.mp.ArcGISProject("CURRENT")`、活动视图相机、图层 CIM 定义、布局
> 导出等接口在 GeoScene Pro 中的实际形态与可用性，**全部未经真实 GeoScene
> Pro 环境验证**。本包的第一用途，就是拿去一台装有 GeoScene Pro 的机器上
> 先跑 `scripts/probe_api.py` 与实时桥的 discover，把兼容性逐项核验清楚
> （核验清单见 [docs/CALIBRATION.md](docs/CALIBRATION.md) 的对照表）——
> 在核验完成之前，不要把本包当作"已可用的 GeoScene 工具"对外宣称，
> 更不要拿 ArcGIS Pro 上的结论冒充 GeoScene 的验证结果。
> 另一重易混点：同一台机器上若同时装有 Esri ArcGIS Pro，它的 arcpy 与
> GeoScene 的 arcpy 导入路径相同、接口同名。preflight / probe 会原样回报
> GetInstallInfo 的 **ProductName / InstallDir**（product_clue 字段），
> 先确认连上的是 GeoScene 的 arcpy，再谈兼容性。

## 衍生来源

本包由同合集仓的 **arcgis-pro-bridge**（ArcGIS Pro 子包）逐文件衍生：
品牌、工具前缀、端口、环境发现线索按 GeoScene Pro 改造，桥的行为逻辑与
安全纪律保持一致。两包的差异点与本包特有的兼容性核验要求，见
`docs/CALIBRATION.md`。除本节与兼容性说明外，本包文档不再引用该来源包。

## 项目由来

这两年，CAD、Blender 等工科软件陆续出现了让 AI Agent 直接接入、操作当前工程的服务，Agent 不再只能隔着文件格式猜内容。GIS 与遥感这边还基本是空白——看到别的工科行业一直在涌现这种服务，就想为我们 GIS/遥感也加一个，于是有了这个系列的桥：让 Agent 以受控、可审计的方式操作 GIS 工程，而不是直接读写二进制文件。GeoScene 是国产 GIS 平台，本包让它也进入这个系列；因为它与 ArcGIS Pro 同源，本包得以低成本衍生，但"同源"必须先经实机核验才算数。

## 两种模式

### 无头桥（headless）

外部脚本操作工程文件，适合盘点、备份、批处理。三件动作全部只读或只读原件：

| 动作 | 说明 |
|---|---|
| `preflight` | 环境与许可预检：定位 GeoScene Pro 自带 Python、arcpy 可导入、版本/许可级别与**产品身份线索（product_clue）**回报 |
| `backup` | 给工程文件生成带时间戳的备份副本并回报 sha256；同名 .gdb 文件夹整体复制 |
| `inspect` | 工程盘点：先把 .aprx 复制到临时目录再打开（原件零接触），输出地图/图层/表/布局的 JSON 清单 |

**必须先知道的事实**：无头模式是外部进程打开 .aprx 文件，**只能看到上次保存
到磁盘的状态，看不到 GeoScene Pro 界面里的未保存修改**。inspect 的输出固定
标注 `mode: headless-saved-state` 并附说明，本项目把这条边界写进输出本身，
不让盘点结果被误当成实时状态。要操作界面里的当前工程，请用实时桥。

另有校准/核验探针 `scripts/probe_api.py`：首次部署或版本变更时运行一次，
输出本机 arcpy 的产品身份（ProductName / InstallDir 原文）与关键类的真实
方法清单，并实测 `ArcGISProject("CURRENT")` 在当前进程的可用性，
供维护者据此判断兼容性、收紧桥接脚本。操作手册见 `SKILL.md`，脚本在 `scripts/`。

### 实时桥（live）

Blender MCP 式接入：桥脚本跑在 **GeoScene Pro 进程内的 Python 窗口或 Notebook**
里，经 `arcpy.mp.ArcGISProject("CURRENT")` 拿到当前打开的工程（该接口在
GeoScene Pro 中的可用性待实机核验，见文首声明），在本机开一个 localhost
服务；你的 AI Agent / MCP 客户端经一个纯标准库的 stdio MCP 服务端调用工具，
操作实时反映在 GUI 界面里。
使用说明见 `live/LIVE.md`，自检脚本 `live/selftest.py`。

## 架构

```
┌──────────────────────────── GeoScene Pro 进程 ──────────────────────────┐
│  Python 窗口 / Notebook 里 exec live/inapp_bridge.py                      │
│  → ArcGISProject("CURRENT") 拿当前工程 → TCP 服务 127.0.0.1:47619（token 鉴权）│
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ 行分隔 JSON（请求须带 token）
┌──────────────────────────────────▼───────────────────────────────────────┐
│  live/mcp_server.py（纯 Python 标准库，stdio MCP 服务端）                  │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ MCP (stdio)
┌──────────────────────────────────▼───────────────────────────────────────┐
│  你的 AI Agent / MCP 客户端（12 个 geoscene_* 工程工具 + ping）            │
└───────────────────────────────────────────────────────────────────────────┘

无头桥：Agent → scripts/geoscene_bridge.py（子命令）→ arcpy → 工程文件副本
```

## 快速上手

### 无头桥

把整个仓库放到你的机器上，让你的 AI Agent 读 `SKILL.md` 并严格按它执行。
第一份任务可以这样下达（结果式表述，路径按你的实际改）：

> 读 `<仓库路径>/SKILL.md` 并严格按它执行。目标结果：
> (1) 完成本机 GeoScene Pro 环境发现与 preflight，回报 JSON 原文，
> 并指出 product_clue 里 ProductName / InstallDir 的原文（先确认是 GeoScene）；
> (2) 运行 probe_api.py 并完整回传输出；
> (3) 对工程 `<你的某个 .aprx 路径>` 先 backup 再 inspect，回报两份 JSON 原文，
> 并在汇报 inspect 结果时注明"此为已保存状态，不含界面未保存修改"。
> 全程对原件零写入；许可或版本报错即停并回报原文，不许换环境反复试探，
> 不要改动与本任务无关的既有项目环境（包括 GeoScene Pro 自带 Python 环境）。

验收清单：

- [ ] preflight 的 JSON 中 `checks.arcpy_import` 为 ok，且 product_clue 显示产品为 GeoScene（不是 Esri ArcGIS）
- [ ] probe 输出包含 PRODUCT CLUE 两行与 ArcGISProject / Map / Layer / Layout 四个类的完整方法清单
- [ ] backup 生成了带时间戳的副本且 sha256 非空（有同名 .gdb 时文件夹副本一并生成）
- [ ] inspect 的 JSON 里地图名、图层名、数据源与 GeoScene Pro 里已保存的状态一致，且带 headless-saved-state 标注
- [ ] 原件的修改时间未变（证明只读纪律守住了）

### 实时桥

1. 打开 GeoScene Pro，打开要操作的工程与地图视图。
2. 打开 GeoScene Pro 的 Python 窗口，执行：
   `exec(open(r"<包路径>\live\inapp_bridge.py", encoding="utf-8").read())`
   看到 `[geoscene-live-bridge] listening on 127.0.0.1:47619` 即桥已上线；
   本次 token 会写到 `~/.geoscene-live-bridge.token`，MCP 服务端自动读取，无需手填。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端：
   - command：Python 3 解释器（建议 3.11+；不需要装 arcpy，它只做转发）
   - args：`<包路径>\live\mcp_server.py`
   注册后客户端应能列出 13 个 geoscene_* 工具（12 个工程工具 + ping）。

接入前建议先在 Python 3（建议 3.11+）里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token，共 6 项）。
注意：自检只验证包自身的协议层，**不构成对 GeoScene Pro 的兼容性证明**；
兼容性核验必须按 docs/CALIBRATION.md 在实机完成。

## 工具清单

### 实时桥（13 个工具：12 个工程工具 + ping）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；视图级＝只改
显示状态、可逆、不落盘；写类＝改变工程内容，全部带 confirm=true 闸
（confirm 只能在用户明确同意后由 Agent 填入）。

| 工具 | 作用 | 风险 |
|---|---|---|
| geoscene_ping | 桥是否在线（连通性检查，不计入工程工具数） | 只读 |
| geoscene_discover | 发现当前工程接入方式 + 现场 API 清单 + 产品身份字段（兼容性核验用） | 只读 |
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

### 无头桥（3 个动作）

`preflight`（只读）、`backup`（只读原件，生成副本）、`inspect`（只读，
操作的是临时副本，且结果为已保存状态）。无头桥不包含任何写业务动作。

## 与来源包的差异

本包与同合集仓的 Pro 版子包行为逻辑一致，差异刻意只保留在四处：

1. **品牌与命名**：包名、工具前缀（geoscene_*）、桥名、端口（47619）、
   token 文件名全部按 GeoScene 区分，两个桥可以在同一台机器上并行运行、互不串扰。
2. **环境发现线索**：preflight / probe 的候选路径换成 GeoScene Pro 的安装
   线索（注册表 GeoScene 键、GeoScene 安装目录启发式扫描），同时保留 arcpy
   导入路径本身。
3. **产品身份回报**：preflight 增加 product_clue、discover 增加
   product_name / install_dir 原文字段——因为两个产品的 arcpy 同名同接口，
   不先确认身份，兼容性结论就无从谈起。
4. **文档定位**：本包的第一里程碑不是"功能"，而是**兼容性核验**：
   docs/CALIBRATION.md 给出与来源包未验证项逐项对应的核验对照表。

工具面同样刻意收窄：除连通性检查 ping 外只有 12 个工程工具，**不提供任意
代码执行工具**，也不提供任意 GP 工具调用口。能力边界小是设计目标，不是缺陷。

## 安全模型

- **仅本机**：实时桥只监听 127.0.0.1，不对外暴露；每次启动生成随机 token，
  请求必须带对 token 才执行，token 经本地文件在桥与 MCP 服务端之间传递。
- **写操作 confirm 闸**：内容级写工具（加入数据、保存工程）缺 `confirm=true`
  一律拒绝执行；confirm 只能在用户明确同意后填入。
- **没有任意代码执行面**：桥内不存在 eval/exec 外部输入、任意 GP 调用通道；
  Agent 请求工具之外的动作时，桥只会返回未知工具错误。
- **无头模式只操作副本**：inspect 先复制到临时目录再打开；backup 只生成新副本、
  从不覆盖；任何写需求都先 backup、只改工作副本，原件零写入。
- **如实报错纪律**：调不通的工具返回结构化错误并附现场方法清单，配套文档明确
  要求 Agent 如实回报，不许把失败粉饰成成功；许可/版本报错即停，不许反复试探。

## 状态声明（请先读这一段）

- **v0.2（2026-10-24）**：协议层与工程纪律升级（自 SuperMap 实机校准迁移通用教训）：selftest 改后台线程 + 队列读行（删 `select`，修 Windows 管道问题）；token 文件位置可用环境变量 `GEOSCENE_BRIDGE_TOKEN_FILE` 覆盖；新增 `scripts/verify_project.py`（只读盘点 / `--copy-to` 迁移验收，含 product_clue）与 `ENGINEERING-PLAYBOOK.md`。工具清单、端口（47619）、confirm 闸与 BAD_TOKEN 语义不变；**与 GeoScene Pro 的兼容性仍未经实机验证**，口径不变。

- 无头桥：已在无 GeoScene Pro 的环境验证脚本语法、backup 的真实复制 + sha256、
  无 arcpy 环境下的结构化报错 JSON 与退出码（ARCPY_NOT_AVAILABLE / FILE_NOT_FOUND）；
  arcpy 实机路径（preflight 的产品身份与许可回报、inspect 的真实盘点）待使用者
  在 GeoScene Pro 机器上核验。
- 实时桥：已验证端到端协议层（`live/selftest.py` 6/6 PASS：握手、13 工具清单、
  ping 转发、discover 结构化回报、保存闸门、错误 token 拒绝）。
  **实时模式尚未在真实 GeoScene Pro 上做过任何验证**，且其所依赖的 API 与
  ArcGIS Pro 兼容这一前提本身也是待核验项：`ArcGISProject("CURRENT")`
  的会话形态、活动视图相机（activeView.camera）的缩放写法、图层标注的 CIM
  定义回写、Layout/MapFrame 的导出签名，桥内均采用多策略尝试 + 命中策略
  回报（via 字段）的实验性实现。首次实机使用必须按
  [docs/CALIBRATION.md](docs/CALIBRATION.md) 的顺序逐项核验
  （先确认产品身份，再 discover 钉死实时接入策略，写类工具只在工程副本上验证）。
- arcpy.mp 在不同版本间有 API 增减，桥接脚本会把命中的策略记进输出
  （`opened_via` / `api_path` / `via`），核验后请据实收紧并注明实机版本
  （GeoScene Pro 版本 + arcpy 版本）。

## 环境要求

- GeoScene Pro 及其自带 Python 环境；实时桥需要能在 GeoScene Pro 的
  Python 窗口或 Notebook 里执行脚本。
- Python 3.11+（建议口径；MCP 服务端与自检只需要标准库）。
- 任一支持 stdio 的 MCP 客户端 / AI Agent（实时桥）；无头桥只需要能执行脚本的 Agent。
- 一份你自己合法持有的 GeoScene Pro 许可（本项目不提供、不绕过任何许可机制；
  arcpy 无法脱离桌面端安装单独安装或运行）。

## 目录结构

```
geoscene/（gis-agent-bridges 合集仓子目录）
├── README.md               本文件
├── SKILL.md                无头桥操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md              版本演进、兼容性核验清单、后续候选路线评估
├── docs/
│   └── CALIBRATION.md      实机兼容性核验与校准指南（对照表、顺序、验收标准、回报格式、红线）
├── scripts/
│   ├── geoscene_bridge.py  无头桥脚本（preflight / backup / inspect，单行 JSON 输出）
│   └── probe_api.py        兼容性探针，输出产品身份与本机 arcpy 的真实方法清单、CURRENT 可用性
└── live/
    ├── inapp_bridge.py     GeoScene Pro 应用内桥（localhost 服务，单文件可 exec）
    ├── mcp_server.py       MCP 服务端（stdio 转发，纯标准库）
    ├── selftest.py         实时桥一键自检（无 GeoScene Pro 环境可跑协议层）
    └── LIVE.md             实时桥使用说明（启动、工具清单与风险等级、纪律）
```

## 免责声明

本项目是独立的第三方开源工具，与易智瑞（GeoScene 的厂商）及 Esri
（Environmental Systems Research Institute）均没有任何隶属、授权或合作关系；
GeoScene、ArcGIS、ArcGIS Pro、ArcPy、Esri 等名称与商标归其各自权利方所有，
本项目仅为互操作目的提及。使用本工具操作 GeoScene Pro 工程，需要你自备
正版 GeoScene Pro 软件与许可，并自行对操作结果负责。本工具按现状提供，
不附带任何明示或默示担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
