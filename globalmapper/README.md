# globalmapper-bridge

> **English** — globalmapper-bridge lets an AI agent work with Global Mapper
> (Blue Marble Geographics) workspaces in a controlled, auditable way, through
> the official `globalmapper` Python module that ships with Global Mapper Pro.
> It is **headless-first**: inventory, backup and inspection of workspace files
> (*.gmw), plus a stdio MCP server that can open workspaces, list layers and
> export images. Global Mapper offers only a *half-session* interface — scripts
> run in the desktop Script Editor with "Run Script in the Context of the Main
> View" can touch the currently loaded layers — so this bridge is deliberately
> **semi-live, not a resident real-time bridge**: view-level tools (layer
> visibility, zoom) refuse to run outside a script context and say so in a
> structured way. Nothing in this package has been calibrated against a real
> Global Mapper installation yet — see `docs/CALIBRATION.md`.

让 AI Agent 通过 Global Mapper 官方 Python 模块 **globalmapper**（仅随
Global Mapper **Pro** 版提供）受控操作 Global Mapper 工程（工作区 *.gmw），
而不是让 Agent 直接猜二进制/文本格式。所有动作都是有限、受控、带安全闸的；
动作之外不许 Agent 自行发挥。

## 项目由来

这两年，CAD、Blender 等工科软件陆续出现了让 AI Agent 直接接入、操作当前工程的服务，GIS 与遥感这边还基本是空白。本包是「GIS Agent 桥」系列的一员（同系列已有 SuperMap、ArcGIS Pro / ArcMap 等桥），把同一套受控桥接打法带到 Global Mapper：让 Agent 以受控、可审计的方式盘点、备份与有限操作 Global Mapper 工程。

## 先说清的定位与边界（请先读这一段）

- **无头为主**：本包的主力是无头桥（环境预检、工作区备份、工作区盘点）与
  MCP 服务端的打开/列图层/导出能力，这些只依赖 `globalmapper` 模块本身。
- **只有“半个会话”接口**：Global Mapper 桌面端的 Script Editor 在勾选
  "Run Script in the Context of the Main View" 时，脚本能利用当前工作区已
  加载的图层——这是半个当前会话接口，**没有** SuperMap iDesktopX / ArcGIS
  Pro 那样可常驻的应用内桥形态。本包**不宣称完整实时接入**。
- **视图类工具有上下文闸**：图层显隐、缩放在无头上下文下一律结构化返回
  `NOT_IN_MAIN_VIEW_CONTEXT`，只有探测到脚本上下文（或启动方如实声明
  main-view 上下文）时才尝试执行；缩放即便在脚本上下文下也可能因公开 API
  没有对应入口而返回 `NOT_SUPPORTED`，这属于预期行为，必须如实回报。
- **API 签名未实机校准**：`globalmapper` 模块的函数名/签名随大版本差异较大，
  桥内一律多策略尝试并回报命中的函数名（via 字段），探针
  `scripts/probe_api.py` 用来钉死本机版本的真实命中表。首次实机使用必须按
  [docs/CALIBRATION.md](docs/CALIBRATION.md) 逐项校准。

## 两种运行形态

### 无头桥（headless，scripts/）

外部脚本操作工程文件，适合盘点、备份、批处理。三件动作全部只读或只读原件：

| 动作 | 说明 |
|---|---|
| `preflight` | 环境预检：globalmapper 模块可导入、版本与候选函数命中、安装线索 |
| `backup` | 给 .gmw 生成带时间戳的备份副本并回报 sha256，附同名数据与引用文件提示 |
| `inspect` | 工程盘点：优先用模块打开临时副本列图层；模块不可用时退化为解析 .gmw 文本片段（mode=headless-partial-parse，结果可能不完整，如实标注） |

操作手册见 `SKILL.md`；校准探针 `scripts/probe_api.py` 首次部署或版本变更时
运行一次，输出本机模块的候选函数命中清单与公开名称全表。

### MCP 服务端（live/，半实时）

纯标准库 stdio MCP 服务端，在自己进程里直调 `globalmapper` 模块
（无常驻应用内桥）。Agent 经它可以：打开 .gmw、列图层、导出图片；
图层显隐/缩放仅在脚本上下文下放行。使用说明见 `live/LIVE.md`，
自检脚本 `live/selftest.py`（无 Global Mapper 环境可跑协议层）。

## 架构

```
无头桥：
  AI Agent → scripts/gm_bridge.py（子命令）→ globalmapper 模块 → 工作区副本
           → 模块不可用时退化：只读解析 .gmw 文本片段（部分结果）

MCP 服务端（半实时）：
┌──────────────────────────────────────────────────────────────┐
│  live/mcp_server.py（纯 Python 标准库，stdio MCP 服务端）        │
│  进程内 import globalmapper 模块直调（无常驻应用内桥）           │
│  context 探测：headless / script-context-suspected /           │
│               script-main-view（启动方如实声明）                 │
└──────────────────────────────┬───────────────────────────────┘
                               │ MCP (stdio)
┌──────────────────────────────▼───────────────────────────────┐
│  你的 AI Agent / MCP 客户端（7 个 globalmapper_* 工具）          │
└──────────────────────────────────────────────────────────────┘

文件投递备选（见 live/LIVE.md）：Agent 写作业脚本 → 用户在 Script Editor
以主视图上下文运行 → 结果 JSON 写回约定目录 → Agent 读取。无常驻、无实时，
但在脚本上下文形态未校准前是最稳妥的“半实时”通道。
```

## 快速上手

### 无头桥

把整个仓库放到你的机器上，让你的 AI Agent 读 `SKILL.md` 并严格按它执行。
第一份任务可以这样下达（结果式表述，路径按你的实际改）：

> 读 `<仓库路径>/SKILL.md` 并严格按它执行。目标结果：
> (1) 完成本机 Global Mapper Pro 环境发现与 preflight，回报 JSON 原文；
> (2) 运行 probe_api.py 并完整回传输出；
> (3) 对工作区 `<你的某个 .gmw 路径>` 先 backup 再 inspect，回报两份 JSON 原文。
> 全程对原件零写入；模块或版本报错即停并回报原文，不许换环境反复试探，
> 不要改动与本任务无关的既有项目环境。

验收清单：

- [ ] preflight 的 JSON 中 `globalmapper_import` 为 ok（否则先解决 Pro 版/模块路径，别往下走）
- [ ] probe 输出包含各功能组的候选命中清单
- [ ] backup 生成了带时间戳的副本且 sha256 非空，referenced_files 已核对存在性
- [ ] inspect 的 JSON 里图层名与 Global Mapper 界面里看到的一致（partial-parse 模式下只作参考）
- [ ] 原件的修改时间未变（证明只读纪律守住了）

### MCP 服务端

1. 选一个能 import 到 `globalmapper` 模块的 Python 解释器
   （Global Mapper Pro 自带/配套的 Python 环境；先用 probe 确认）。
2. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端：
   - command: 上一步的 Python 解释器
   - args: `<仓库路径>\live\mcp_server.py`
   注册后客户端应能列出 7 个 globalmapper_* 工具。
3. 接入前先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
   （initialize / tools/list=7 / BAD_TOKEN 闸 / ping / discover，共 5 项）。

## 工具清单

### MCP 服务端（7 个工具）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；
视图级＝只改显示状态、可逆，但仅脚本上下文可用。

| 工具 | 作用 | 风险 |
|---|---|---|
| globalmapper_ping | 服务端在线、模块可用性与当前上下文 | 只读 |
| globalmapper_discover | 模块/版本/候选函数命中/运行上下文（校准用） | 只读 |
| globalmapper_workspace_info | 当前工作区概览（上下文、已打开工作区、图层数） | 只读 |
| globalmapper_list_layers | 列图层（可传 workspace 先打开某个 .gmw） | 只读 |
| globalmapper_export_workspace_image | 导出当前已加载图层为栅格图片（以文件真落盘为准） | 只读出文件 |
| globalmapper_set_layer_visible | 设置图层显隐（仅脚本上下文；无头返回 NOT_IN_MAIN_VIEW_CONTEXT） | 视图级 |
| globalmapper_zoom_to_layer | 主视图缩放到图层（仅脚本上下文；可能 NOT_SUPPORTED） | 视图级 |

### 无头桥（3 个动作）

`preflight`（只读）、`backup`（只读原件，生成副本）、`inspect`（只读，
模块路线操作的是临时副本，文本路线只读字节）。无头桥不包含任何写业务动作。

## 安全模型

- **原件只读**：inspect 的模块路线先复制到临时目录再打开；backup 只生成新
  副本、从不覆盖；文本解析路线只读字节。本包没有任何写业务动作。
- **上下文闸（诚实闸）**：视图类工具必须有脚本上下文证据才放行；
  严禁用设置环境变量的方式伪造 main-view 上下文骗过闸门（见校准红线）。
- **可选 token 闸**：设置环境变量 `GM_BRIDGE_TOKEN` 后，MCP 的 tools/call
  必须在 arguments 里带匹配的 `_token`，否则以 BAD_TOKEN 拒绝——为将来
  非 stdio 传输预留，本机 stdio 直连可不设。
- **如实报错纪律**：调不通的工具返回结构化错误并附尝试记录，配套文档明确
  要求 Agent 如实回报，不许把失败粉饰成成功；模块/版本报错即停。

## 状态声明

- 无头桥：已在无 Global Mapper 的环境验证脚本语法、backup 的真实复制 +
  sha256、模块缺失环境下的报错 JSON 与退出码，以及 inspect 退化到文本
  部分解析的完整链路；globalmapper 模块实机路径待使用者校准。
- MCP 服务端：已验证协议层（`live/selftest.py` 5/5 PASS：握手、7 工具清单、
  BAD_TOKEN 闸、ping、discover 结构化回报）。**与 Global Mapper 本体的对接
  （模块加载/枚举签名、脚本上下文形态、视图工具、导出签名）全部未实机验证**，
  首次实机使用必须按 [docs/CALIBRATION.md](docs/CALIBRATION.md) 逐项校准。
- globalmapper 不同大版本的 API 命名有差异，桥接脚本会把命中的策略记进输出
  （`opened_via` / `via`），校准后请据实收紧并注明实机版本。

## 环境要求

- **Global Mapper Pro**（Python `globalmapper` 模块仅 Pro 版提供；
  标准版只有 .gms 脚本语言，本包的模块路线不可用）。
- 与之配套的 Python 3 环境（能 import globalmapper 模块）。
- 任一支持 stdio 的 MCP 客户端 / AI Agent（MCP 服务端）；无头桥只需要能执行脚本的 Agent。
- 一份你自己合法持有的 Global Mapper 许可（本项目不提供、不绕过任何许可机制）。

## 目录结构

```
globalmapper/
├── README.md            本文件
├── SKILL.md             无头桥操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md           版本演进、待实机校准清单、后续候选路线评估
├── docs/
│   └── CALIBRATION.md   实机校准指南（顺序、验收标准、回报格式、红线）
├── scripts/
│   ├── gm_bridge.py     无头桥脚本（preflight / backup / inspect，单行 JSON 输出）
│   └── probe_api.py     校准探针，输出本机 globalmapper 模块的候选函数命中清单
└── live/
    ├── mcp_server.py    MCP 服务端（stdio、纯标准库、进程内直调模块；无常驻应用内桥）
    ├── selftest.py      MCP 服务端一键自检（无 Global Mapper 环境可跑协议层）
    └── LIVE.md          半实时工作方式说明（两种上下文、文件投递备选、工具与纪律）
```

## 免责声明

本项目是独立的第三方开源工具，与 Blue Marble Geographics 没有任何隶属、
授权或合作关系；Global Mapper 等名称与商标归其权利方所有，本项目仅为
互操作目的提及。使用本工具操作 Global Mapper 工程，需要你自备正版
Global Mapper 软件与许可，并自行对操作结果负责。本工具按现状提供，
不附带任何明示或默示担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
