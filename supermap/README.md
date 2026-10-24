# supermap-gis-bridge

> **English** — supermap-gis-bridge lets an AI agent operate SuperMap GIS projects
> through SuperMap's official Python component (iobjectspy), in two modes: a
> *headless bridge* that inventories / backs up workspace files by running scripts
> against copies only, and a *live MCP bridge* that runs inside SuperMap iDesktopX
> (Blender-MCP style) so any MCP client can inspect and operate the workspace you
> currently have open, in real time. The live mode's file-fallback path has been calibrated on a real
> iDesktop 10i installation (2026-10-24, 13/13 tools verified); the real-time
> iDesktopX mode is still experimental — see `docs/CALIBRATION-RESULTS-20261024.md`.

让 AI Agent 通过 SuperMap 官方 Python 组件 **iobjectspy** 操作 SuperMap 工程
（工作空间 *.smwu / *.sxwu、数据源 *.udbx）的受控桥接工具，而不是让 Agent 直接
读写二进制工程文件。所有动作都是有限、受控、带安全闸的；动作之外不许 Agent 自行发挥。

## 项目由来

这两年，CAD、Blender 等工科软件陆续出现了让 AI Agent 直接接入、操作当前工程的服务，Agent 不再只能隔着文件格式猜内容。GIS 与遥感这边还基本是空白——看到别的工科行业一直在涌现这种服务，就想为我们 GIS/遥感也加一个，于是有了这个桥：让 Agent 以受控、可审计的方式操作 SuperMap 工程，而不是直接读写二进制文件。

## 两种模式

### 无头桥（headless）

外部脚本操作工程文件，适合盘点、备份、批处理。三件动作全部只读或只读原件：

| 动作 | 说明 |
|---|---|
| `preflight` | 环境与许可预检：iobjectspy 可导入、iObjects Java 路径、许可冒烟 |
| `backup` | 给工作空间文件生成带时间戳的备份副本并回报 sha256 |
| `inspect` | 工程盘点：先把工作空间复制到临时目录再打开（原件零接触），输出数据源/数据集/地图的 JSON 清单 |

另有校准探针 `scripts/probe_api.py`：首次部署或版本变更时运行一次，输出本机
iobjectspy 关键类的真实方法清单，供维护者据此收紧桥接脚本。
操作手册见 `SKILL.md`，脚本在 `scripts/`。

### 实时桥（live）

Blender MCP 式接入：桥脚本跑在 **iDesktopX 进程内的 Python 窗口**里，拿到当前
打开的工作空间，在本机开一个 localhost 服务；你的 AI Agent / MCP 客户端经一个
纯标准库的 stdio MCP 服务端调用工具，操作实时反映在 GUI 界面里。
使用说明见 `live/LIVE.md`，自检脚本 `live/selftest.py`。没有 iDesktopX 时，桥也可由
`live/run_bridge_copy.py` 在**工作空间副本**上以文件回退模式启动（iDesktop 10i
已实机校准），或把 .smwu 拖到 `live/start_bridge.cmd` 上启动；此模式下界面不刷新，
不得称实时接入。

## 架构

```
┌──────────────────────────── iDesktopX 进程 ────────────────────────────┐
│  Python 窗口 exec live/inapp_bridge.py                                   │
│  → 拿到当前工作空间（多策略发现） → TCP 服务 127.0.0.1:47615（token 鉴权） │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ 行分隔 JSON（请求须带 token）
┌──────────────────────────────────▼───────────────────────────────────────┐
│  live/mcp_server.py（纯 Python 标准库，stdio MCP 服务端）                  │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ MCP (stdio)
┌──────────────────────────────────▼───────────────────────────────────────┐
│  你的 AI Agent / MCP 客户端（13 个 supermap_* 工具）                       │
└───────────────────────────────────────────────────────────────────────────┘

无头桥：Agent → scripts/supermap_bridge.py（子命令）→ iobjectspy → 工程文件副本
```

## 快速上手

### 无头桥

把整个仓库放到你的机器上，让你的 AI Agent 读 `SKILL.md` 并严格按它执行。
第一份任务可以这样下达（结果式表述，路径按你的实际改）：

> 读 `<仓库路径>/SKILL.md` 并严格按它执行。目标结果：
> (1) 完成本机 SuperMap 环境发现与 preflight，回报 JSON 原文；
> (2) 运行 probe_api.py 并完整回传输出；
> (3) 对工作空间 `<你的某个 .smwu 路径>` 先 backup 再 inspect，回报两份 JSON 原文。
> 全程对原件零写入；许可或版本报错即停并回报原文，不许换环境反复试探，
> 不要改动与本任务无关的既有项目环境。

验收清单：

- [ ] preflight 的 JSON 中 `license_smoke` 为 ok（否则先解决许可，别往下走）
- [ ] probe 输出包含 Workspace / Datasource / Map 三个类的完整方法清单
- [ ] backup 生成了带时间戳的副本且 sha256 非空
- [ ] inspect 的 JSON 里数据源别名、数据集名称/类型与 iDesktop 里看到的一致
- [ ] 原件的修改时间未变（证明只读纪律守住了）

### 实时桥

1. 打开 iDesktopX，打开要操作的工作空间与地图。
2. 打开 iDesktopX 的 Python 窗口，执行：
   `exec(open(r"<仓库路径>\live\inapp_bridge.py", encoding="utf-8").read())`
   看到 `[supermap-live-bridge] listening on 127.0.0.1:47615` 即桥已上线；
   本次 token 会写到 `~/.supermap-live-bridge.token`，MCP 服务端自动读取，无需手填。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端：
   - command：任意 Python 3 解释器（不需要装 iobjectspy，它只做转发）
   - args：`<仓库路径>\live\mcp_server.py`
   注册后客户端应能列出 13 个 supermap_* 工具。

接入前建议先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token，共 6 项）。

## 工具清单

### 实时桥（13 个工具）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；视图级＝只改
显示状态、可逆、不落盘；写类＝改变工程内容，全部带 confirm=true 闸
（confirm 只能在用户明确同意后由 Agent 填入）。

| 工具 | 作用 | 风险 |
|---|---|---|
| supermap_ping | 桥是否在线 | 只读 |
| supermap_discover | 发现当前工作空间接入方式 + 现场 API 清单（校准用） | 只读 |
| supermap_workspace_info | 当前工作空间概览（数据源数/地图数/接入模式） | 只读 |
| supermap_list_datasources | 列数据源（别名、引擎） | 只读 |
| supermap_list_datasets | 列数据集（可按数据源别名过滤） | 只读 |
| supermap_list_maps | 列地图名 | 只读 |
| supermap_list_layers | 列某地图的图层（下标/名称/显隐） | 只读 |
| supermap_export_map_image | 导出地图为 PNG 到指定路径（以文件真落盘为准） | 只读出文件 |
| supermap_set_layer_visible | 设置图层显隐 | 视图级 |
| supermap_zoom_to_dataset | 地图视图缩放到数据集范围 | 视图级 |
| supermap_add_dataset_to_map | 把数据集加入地图（须 confirm=true） | **写** |
| supermap_make_label_thematic | 按字段做标签专题图（须 confirm=true） | **写** |
| supermap_save_workspace | 保存当前工作空间（须 confirm=true） | **写** |

### 无头桥（3 个动作）

`preflight`（只读）、`backup`（只读原件，生成副本）、`inspect`（只读，
操作的是临时副本）。无头桥不包含任何写业务动作。

## 安全模型

- **仅本机**：实时桥只监听 127.0.0.1，不对外暴露；每次启动生成随机 token，
  请求必须带对 token 才执行，token 经本地文件在桥与 MCP 服务端之间传递。
- **写操作 confirm 闸**：内容级写工具（加数据集进地图、标签专题图、保存工作空间）
  缺 `confirm=true` 一律拒绝执行；confirm 只能在用户明确同意后填入。
- **无头模式只操作副本**：inspect 先复制到临时目录再打开；backup 只生成新副本、
  从不覆盖；任何写需求都先 backup、只改工作副本，原件零写入。
- **如实报错纪律**：调不通的工具返回结构化错误并附现场方法清单，配套文档明确
  要求 Agent 如实回报，不许把失败粉饰成成功；许可/版本报错即停，不许反复试探。

## 状态声明（请先读这一段）

- 无头桥：已于 2026-10-24 在 iDesktop 10i(2020) + iobjectspy 10.1.0 环境实机
  校准通过（preflight 许可冒烟、backup 真实复制 + sha256、inspect 对真实工作
  空间盘点，含相对路径数据源连带复制），见
  [docs/CALIBRATION-RESULTS-20261024.md](docs/CALIBRATION-RESULTS-20261024.md)。
- 实时桥：已验证端到端协议层（`live/selftest.py` 6/6 PASS：握手、13 工具清单、
  ping 转发、discover 结构化回报、保存闸门、错误 token 拒绝）。
  **文件回退模式已实机校准**：2026-10-24 在没有 iDesktopX 的 iDesktop 10i
  环境上，实时桥以 file-fallback 模式（操作带时间戳的工作空间副本、GUI 不刷新）
  在 13/13 工具上实机通过，写类在副本上验证持久化、原件未变，见
  [docs/CALIBRATION-RESULTS-20261024.md](docs/CALIBRATION-RESULTS-20261024.md)。
  **iDesktopX 实时模式仍未校准**：当前工作空间的注入方式与部分 API 签名仍因
  版本而异，桥内采用多策略尝试 + 命中策略回报（via 字段）的实现。首次在有 X
  的环境使用必须按 [docs/CALIBRATION.md](docs/CALIBRATION.md) 的顺序逐项校准
  （先 discover 钉死实时接入策略，操作类工具只在工作空间副本上验证）。
- iobjectspy 不同小版本的 API 命名有差异，桥接脚本会把命中的策略记进输出
  （`opened_via` / `api_path` / `via`），校准后请据实收紧并注明实机版本。

## 环境要求

- SuperMap iDesktopX（实时桥实时模式）或 iDesktop 10i（无头桥，以及实时桥
  文件回退模式——已实机校准），
  以及与之版本匹配的 **iobjectspy 10.x** 与 iObjects Java，Java 8+。
- Python 3.x。
- 任一支持 stdio 的 MCP 客户端 / AI Agent（实时桥）；无头桥只需要能执行脚本的 Agent。
- 一份你自己合法持有的 SuperMap 许可（本项目不提供、不绕过任何许可机制）。

## 目录结构

```
supermap-gis-bridge/
├── README.md               本文件
├── SKILL.md                无头桥操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md              版本演进、待实机校准清单、后续候选路线评估
├── docs/
│   ├── CALIBRATION.md      实机校准指南（顺序、验收标准、回报格式、红线）
│   └── CALIBRATION-RESULTS-20261024.md  iDesktop 10i 实机校准结果（环境、13/13 清单、API 事实）
├── scripts/
│   ├── supermap_bridge.py  无头桥脚本（preflight / backup / inspect，单行 JSON 输出）
│   └── probe_api.py        校准探针，输出本机 iobjectspy 的真实方法清单
└── live/
    ├── inapp_bridge.py     iDesktopX 应用内桥（localhost 服务，单文件可 exec）
    ├── mcp_server.py       MCP 服务端（stdio 转发，纯标准库）
    ├── selftest.py         实时桥一键自检（无 SuperMap 环境可跑协议层）
    ├── run_bridge_copy.py  文件回退启动器：在工作空间副本上起桥（原件只读）
    ├── start_bridge.cmd    Windows 拖拽启动器（文件回退模式）
    └── LIVE.md             实时桥使用说明（启动、工具清单与风险等级、纪律）
```

## 免责声明

本项目是独立的第三方开源工具，与北京超图软件股份有限公司（SuperMap）没有任何
隶属、授权或合作关系；SuperMap、iDesktop、iDesktopX、iObjects 等名称与商标归
其权利方所有，本项目仅为互操作目的提及。使用本工具操作 SuperMap 工程，需要你
自备正版 SuperMap 软件与许可，并自行对操作结果负责。本工具按现状提供，
不附带任何明示或默示担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
