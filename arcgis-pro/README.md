# arcgis-pro-bridge

> **English** — arcgis-pro-bridge lets an AI agent operate ArcGIS Pro projects
> through Esri's official Python site package (arcpy), in two modes: a
> *headless bridge* that inventories / backs up project files by running scripts
> against copies only — its output is explicitly labelled as the project's
> **last-saved state**, never as the live GUI state — and a *live MCP bridge*
> that runs inside ArcGIS Pro's own Python window (Blender-MCP style) so any MCP
> client can inspect and operate the project you currently have open, in real
> time. The tool surface is deliberately narrow (12 project tools + ping, no
> arbitrary code execution) and every content-changing tool sits behind an
> explicit confirm gate. The live mode is experimental and has not yet been
> calibrated on a real ArcGIS Pro installation — see `docs/CALIBRATION.md`.

让 AI Agent 通过 Esri 官方 Python 站点包 **arcpy** 操作 ArcGIS Pro 工程
（工程 *.aprx、文件地理数据库 *.gdb）的受控桥接工具，而不是让 Agent 直接
读写二进制工程文件。所有动作都是有限、受控、带安全闸的；动作之外不许 Agent 自行发挥。

本仓库是 GIS Agent 桥系列的一员（同系列另有面向 SuperMap 的 supermap-gis-bridge），
两个仓库共享同一套设计纪律：只读优先、原件零写入、写操作 confirm 闸、
如实报错、实机校准留痕。

## 项目由来

这两年，CAD、Blender 等工科软件陆续出现了让 AI Agent 直接接入、操作当前工程的服务，Agent 不再只能隔着文件格式猜内容。GIS 与遥感这边还基本是空白——看到别的工科行业一直在涌现这种服务，就想为我们 GIS/遥感也加一个，于是有了这个系列的桥：让 Agent 以受控、可审计的方式操作 GIS 工程，而不是直接读写二进制文件。ArcGIS Pro 是这个系列的第二个成员。

## 两种模式

### 无头桥（headless）

外部脚本操作工程文件，适合盘点、备份、批处理。三件动作全部只读或只读原件：

| 动作 | 说明 |
|---|---|
| `preflight` | 环境与许可预检：定位 Pro 自带 Python、arcpy 可导入、版本/许可级别回报 |
| `backup` | 给工程文件生成带时间戳的备份副本并回报 sha256；同名 .gdb 文件夹整体复制 |
| `inspect` | 工程盘点：先把 .aprx 复制到临时目录再打开（原件零接触），输出地图/图层/表/布局的 JSON 清单 |

**必须先知道的事实**：无头模式是外部进程打开 .aprx 文件，**只能看到上次保存
到磁盘的状态，看不到 Pro 界面里的未保存修改**。inspect 的输出固定标注
`mode: headless-saved-state` 并附说明，本项目把这条边界写进输出本身，
不让盘点结果被误当成实时状态。要操作界面里的当前工程，请用实时桥。

另有校准探针 `scripts/probe_api.py`：首次部署或版本变更时运行一次，输出本机
arcpy 关键类的真实方法清单，并实测 `ArcGISProject("CURRENT")` 在当前进程的可用性，
供维护者据此收紧桥接脚本。操作手册见 `SKILL.md`，脚本在 `scripts/`。

### 实时桥（live）

Blender MCP 式接入：桥脚本跑在 **ArcGIS Pro 进程内的 Python 窗口或 Notebook** 里，
经 `arcpy.mp.ArcGISProject("CURRENT")` 拿到当前打开的工程，在本机开一个
localhost 服务；你的 AI Agent / MCP 客户端经一个纯标准库的 stdio MCP 服务端
调用工具，操作实时反映在 GUI 界面里。
使用说明见 `live/LIVE.md`，自检脚本 `live/selftest.py`。

## 架构

```
┌──────────────────────────── ArcGIS Pro 进程 ────────────────────────────┐
│  Python 窗口 / Notebook 里 exec live/inapp_bridge.py                      │
│  → ArcGISProject("CURRENT") 拿当前工程 → TCP 服务 127.0.0.1:47616（token 鉴权）│
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ 行分隔 JSON（请求须带 token）
┌──────────────────────────────────▼───────────────────────────────────────┐
│  live/mcp_server.py（纯 Python 标准库，stdio MCP 服务端）                  │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ MCP (stdio)
┌──────────────────────────────────▼───────────────────────────────────────┐
│  你的 AI Agent / MCP 客户端（12 个 arcgis_* 工程工具 + ping）              │
└───────────────────────────────────────────────────────────────────────────┘

无头桥：Agent → scripts/arcgis_bridge.py（子命令）→ arcpy → 工程文件副本
```

## 快速上手

### 无头桥

把整个仓库放到你的机器上，让你的 AI Agent 读 `SKILL.md` 并严格按它执行。
第一份任务可以这样下达（结果式表述，路径按你的实际改）：

> 读 `<仓库路径>/SKILL.md` 并严格按它执行。目标结果：
> (1) 完成本机 ArcGIS Pro 环境发现与 preflight，回报 JSON 原文；
> (2) 运行 probe_api.py 并完整回传输出；
> (3) 对工程 `<你的某个 .aprx 路径>` 先 backup 再 inspect，回报两份 JSON 原文，
> 并在汇报 inspect 结果时注明"此为已保存状态，不含界面未保存修改"。
> 全程对原件零写入；许可或版本报错即停并回报原文，不许换环境反复试探，
> 不要改动与本任务无关的既有项目环境（包括 Pro 自带 Python 环境）。

验收清单：

- [ ] preflight 的 JSON 中 `checks.arcpy_import` 为 ok，且 Version/LicenseLevel 与本机 Pro 一致
- [ ] probe 输出包含 ArcGISProject / Map / Layer / Layout 四个类的完整方法清单
- [ ] backup 生成了带时间戳的副本且 sha256 非空（有同名 .gdb 时文件夹副本一并生成）
- [ ] inspect 的 JSON 里地图名、图层名、数据源与 Pro 里已保存的状态一致，且带 headless-saved-state 标注
- [ ] 原件的修改时间未变（证明只读纪律守住了）

### 实时桥

1. 打开 ArcGIS Pro，打开要操作的工程与地图视图。
2. 打开 Pro 的 Python 窗口，执行：
   `exec(open(r"<仓库路径>\live\inapp_bridge.py", encoding="utf-8").read())`
   看到 `[arcgis-pro-live-bridge] listening on 127.0.0.1:47616` 即桥已上线；
   本次 token 会写到 `~/.arcgis-pro-live-bridge.token`，MCP 服务端自动读取，无需手填。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端：
   - command：任意 Python 3 解释器（不需要装 arcpy，它只做转发）
   - args：`<仓库路径>\live\mcp_server.py`
   注册后客户端应能列出 13 个 arcgis_* 工具（12 个工程工具 + ping）。

接入前建议先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token，共 6 项）。

## 工具清单

### 实时桥（13 个工具：12 个工程工具 + ping）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；视图级＝只改
显示状态、可逆、不落盘；写类＝改变工程内容，全部带 confirm=true 闸
（confirm 只能在用户明确同意后由 Agent 填入）。

| 工具 | 作用 | 风险 |
|---|---|---|
| arcgis_ping | 桥是否在线（连通性检查，不计入工程工具数） | 只读 |
| arcgis_discover | 发现当前工程接入方式 + 现场 API 清单（校准用） | 只读 |
| arcgis_project_info | 当前工程概览（路径/默认地理数据库/地图数/布局数/接入模式） | 只读 |
| arcgis_list_maps | 列地图（名称、类型） | 只读 |
| arcgis_list_layers | 列某地图的图层（下标/名称/显隐/数据源/是否断裂） | 只读 |
| arcgis_list_tables | 列某地图的独立表（名称、数据源、是否断裂） | 只读 |
| arcgis_list_layouts | 列布局（名称、页面宽高、地图框数） | 只读 |
| arcgis_export_map_image | 导出布局/地图框为 PNG 到指定路径（以文件真落盘为准） | 只读出文件 |
| arcgis_set_layer_visible | 设置图层显隐 | 视图级 |
| arcgis_zoom_to_layer | 活动视图缩放到图层范围 | 视图级 |
| arcgis_set_labels_visible | 开关图层标注显示 | 视图级 |
| arcgis_add_layer_from_path | 把数据路径加入地图（须 confirm=true） | **写** |
| arcgis_save_project | 保存当前工程（须 confirm=true） | **写** |

### 无头桥（3 个动作）

`preflight`（只读）、`backup`（只读原件，生成副本）、`inspect`（只读，
操作的是临时副本，且结果为已保存状态）。无头桥不包含任何写业务动作。

## 同类项目与本包定位

GitHub 上已有面向 ArcGIS Pro 的 MCP 项目，工具数量更多（30 个以上），
其中一些还提供任意 Python 执行、带白名单/黑名单的地理处理调用等能力，
各有侧重。本系列的定位是开源分享、把主流 GIS 软件的桥做齐放在一起方便取用；
本包在这个系列里的侧重有四点：

1. **工具面刻意收窄**：除连通性检查 ping 外只有 12 个工程工具，
   **不提供任意代码执行工具**，也不提供任意 GP 工具调用口。
   这是有意的安全取舍：Agent 能做的事被限定在可枚举、可审计的集合内，
   两个内容级写工具再加 confirm=true 闸。能力边界小，是这个项目的设计目标，不是缺陷。
2. **无头桥的"已保存状态"诚实标注与 JSON 证据纪律**：外部进程打开 .aprx
   只能读到上次存盘的状态——这是 arcpy 的客观边界，本包选择把它明确标出来。
   本包的 inspect 输出固定带 `mode: headless-saved-state` 与口径说明；
   全部动作以单行 JSON 回报结果、命中策略与结构化错误码，作为可复核的证据，
   没有 JSON 的回报一律视为未执行。
3. **完整的校准/验收流程文档**：[docs/CALIBRATION.md](docs/CALIBRATION.md)
   给出从 discover 钉死实时策略、只读工具逐项对界面、写操作只在工程副本上验、
   到命中策略回写收紧并跑自检回归的完整顺序与每项验收标准；
   桥的实验性部分因此有明确的收官路径，而不是停留在"应该能用"。
4. **中文优先文档**：README、SKILL、校准指南均以中文为主体（附英文简介），
   面向中文 GIS 使用者、课程与实训场景，报错对照与回报格式都按中文工作流写。

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

- 无头桥：已在无 ArcGIS Pro 的环境验证脚本语法、backup 的真实复制 + sha256、
  无 arcpy 环境下的结构化报错 JSON 与退出码（ARCPY_NOT_AVAILABLE / FILE_NOT_FOUND）；
  arcpy 实机路径（preflight 的许可回报、inspect 的真实盘点）待使用者在 Pro 机器上校准。
- 实时桥：已验证端到端协议层（`live/selftest.py` 6/6 PASS：握手、13 工具清单、
  ping 转发、discover 结构化回报、保存闸门、错误 token 拒绝）。
  **但实时模式尚未在真实 ArcGIS Pro 上完成校准**：`ArcGISProject("CURRENT")`
  的会话形态、活动视图相机（activeView.camera）的缩放写法、图层标注的 CIM
  定义回写、Layout/MapFrame 的导出签名都因版本而异，桥内采用多策略尝试 +
  命中策略回报（via 字段）的实验性实现。首次实机使用必须按
  [docs/CALIBRATION.md](docs/CALIBRATION.md) 的顺序逐项校准
  （先 discover 钉死实时接入策略，写类工具只在工程副本上验证）。
- arcpy.mp 在 Pro 小版本间有 API 增减，桥接脚本会把命中的策略记进输出
  （`opened_via` / `api_path` / `via`），校准后请据实收紧并注明实机版本。

## 环境要求

- ArcGIS Pro 3.x 及其自带 Python 环境（arcgispro-py3）；实时桥需要能在
  Pro 的 Python 窗口或 Notebook 里执行脚本。
- Python 3.x（MCP 服务端与自检只需要标准库）。
- 任一支持 stdio 的 MCP 客户端 / AI Agent（实时桥）；无头桥只需要能执行脚本的 Agent。
- 一份你自己合法持有的 ArcGIS Pro 许可（本项目不提供、不绕过任何许可机制；
  arcpy 无法脱离 ArcGIS Pro 安装单独安装或运行）。

## 目录结构

```
arcgis-pro-bridge/
├── README.md               本文件
├── SKILL.md                无头桥操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md              版本演进、待实机校准清单、后续候选路线评估
├── docs/
│   └── CALIBRATION.md      实机校准指南（顺序、验收标准、回报格式、红线）
├── scripts/
│   ├── arcgis_bridge.py    无头桥脚本（preflight / backup / inspect，单行 JSON 输出）
│   └── probe_api.py        校准探针，输出本机 arcpy 的真实方法清单与 CURRENT 可用性
└── live/
    ├── inapp_bridge.py     ArcGIS Pro 应用内桥（localhost 服务，单文件可 exec）
    ├── mcp_server.py       MCP 服务端（stdio 转发，纯标准库）
    ├── selftest.py         实时桥一键自检（无 ArcGIS Pro 环境可跑协议层）
    └── LIVE.md             实时桥使用说明（启动、工具清单与风险等级、纪律）
```

## 免责声明

本项目是独立的第三方开源工具，与 Esri（Environmental Systems Research Institute）
没有任何隶属、授权或合作关系；ArcGIS、ArcGIS Pro、ArcPy、Esri 等名称与商标归
其权利方所有，本项目仅为互操作目的提及。使用本工具操作 ArcGIS Pro 工程，需要你
自备正版 ArcGIS Pro 软件与许可，并自行对操作结果负责。本工具按现状提供，
不附带任何明示或默示担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
