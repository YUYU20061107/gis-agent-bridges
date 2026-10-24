# qgis-bridge（gis-agent-bridges 系列）

> **English** — qgis-bridge lets an AI agent operate QGIS projects through
> PyQGIS, in two modes: a *headless bridge* that inventories / backs up project
> files — including a pure-stdlib parser for .qgs/.qgz that works **without
> QGIS installed** — and a *live MCP bridge* that runs inside the QGIS Python
> console (Blender-MCP style) so any MCP client can inspect and operate the
> project you currently have open, in real time. The live mode is experimental
> and has not yet been calibrated on a real QGIS installation — see
> `docs/CALIBRATION.md`. This package is one member of the **gis-agent-bridges**
> collection (sibling bridges for other GIS software share the same safety and
> calibration conventions).

让 AI Agent 通过 QGIS 官方 Python 接口 **PyQGIS** 操作 QGIS 工程
（*.qgs / *.qgz）的受控桥接工具。所有动作都是有限、受控、带安全闸的；
动作之外不许 Agent 自行发挥。

## 与已有同类项目的关系

GitHub 上已经有优秀的先行项目（如 **qgis_mcp** 等），它们证明了
「Agent 接入 QGIS」这条路的价值，本项目向它们致谢。本包是 gis-agent-bridges
系列的一员，定位是**开源分享**：不追求工具数量，与系列内其他软件的桥共享
同一套约定——confirm 安全闸、结构化报错、多策略尝试 + 命中策略回报、
以及一份可照着执行的实机校准规范。取舍上刻意收窄：**不提供任意代码执行
工具**，Processing 也只接受「算法 id + 参数 JSON」，不用它绕过安全模型。

## 两种模式

### 无头桥（headless）

外部脚本操作工程文件，适合盘点、备份、批处理。三件动作全部只读或只读原件：

| 动作 | 说明 |
|---|---|
| `preflight` | 环境预检：qgis 模块可导入性、qgis / qgis_process 命令探测，并回报当前可用的模式 |
| `backup` | 给工程文件生成带时间戳的备份副本并回报 sha256；同时提示同名数据目录/同名数据文件线索 |
| `inspect` | 工程盘点（先复制到临时目录再打开）：**策略一**纯 Python 标准库解析 .qgs XML / .qgz，**不装 QGIS 也能盘点**图层清单、数据源、CRS、图层树与布局；**策略二**在装有 QGIS 时用 QgsApplication 无头打开枚举。命中策略记入 `mode` 字段 |

另有校准探针 `scripts/probe_api.py`：首次部署或版本变更时运行一次，输出本机
PyQGIS 关键类的真实方法清单与 iface / processing 可用性。
操作手册见 `SKILL.md`，脚本在 `scripts/`。

### 实时桥（live）

Blender MCP 式接入：桥脚本跑在 **QGIS 的 Python 控制台**里，拿到当前打开的
工程，在本机开一个 localhost 服务；你的 AI Agent / MCP 客户端经一个纯标准库
的 stdio MCP 服务端调用工具，操作实时反映在 GUI 界面里。
使用说明见 `live/LIVE.md`，自检脚本 `live/selftest.py`。

## 架构

```
┌──────────────────────────── QGIS 进程 ────────────────────────────────┐
│  Python 控制台 exec live/inapp_bridge.py                                │
│  → 拿到当前工程（多策略发现） → TCP 服务 127.0.0.1:47618（token 鉴权）    │
│  → 工具执行尽量投递回 Qt 主线程（调度策略见 discover 回报）               │
└──────────────────────────────────┬────────────────────────────────────┘
                                   │ 行分隔 JSON（请求须带 token）
┌──────────────────────────────────▼────────────────────────────────────┐
│  live/mcp_server.py（纯 Python 标准库，stdio MCP 服务端）                 │
└──────────────────────────────────┬────────────────────────────────────┘
                                   │ MCP (stdio)
┌──────────────────────────────────▼────────────────────────────────────┐
│  你的 AI Agent / MCP 客户端（12 个 qgis_* 工具）                         │
└───────────────────────────────────────────────────────────────────────┘

无头桥：Agent → scripts/qgis_bridge.py（子命令）→ 工程文件副本
        （策略一纯标准库解析 / 策略二 QgsApplication 打开）
```

## 快速上手

### 无头桥

把整个仓库放到你的机器上，让你的 AI Agent 读 `SKILL.md` 并严格按它执行。
第一份任务可以这样下达（结果式表述，路径按你的实际改）：

> 读 `<仓库路径>/qgis/SKILL.md` 并严格按它执行。目标结果：
> (1) 运行 preflight，回报 JSON 原文；
> (2) 运行 probe_api.py 并完整回传输出；
> (3) 对工程 `<你的某个 .qgs/.qgz 路径>` 先 backup 再 inspect，回报两份 JSON 原文。
> 全程对原件零写入；报错即停并回报原文，不许换环境反复试探，
> 不要改动与本任务无关的既有项目环境。

验收清单：

- [ ] preflight 的 JSON 中 `ready_modes` 包含你打算用的模式
- [ ] inspect 的 `mode` 与预期一致（`headless-file-parse` 或 `headless-qgis`）
- [ ] inspect 的 JSON 里图层名、数据源、CRS 与 QGIS 里看到的一致
- [ ] backup 生成了带时间戳的副本且 sha256 非空
- [ ] 原件的修改时间未变（证明只读纪律守住了）

### 实时桥

1. 打开 QGIS，打开要操作的工程。
2. 打开 Python 控制台（菜单「插件 → Python 控制台」，或快捷键 Ctrl+Alt+P），执行：
   `exec(open(r"<仓库路径>\qgis\live\inapp_bridge.py", encoding="utf-8").read())`
   看到 `[qgis-live-bridge] listening on 127.0.0.1:47618` 即桥已上线；
   本次 token 会写到 `~/.qgis-live-bridge.token`，MCP 服务端自动读取，无需手填。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端：
   - command：任意 Python 3 解释器（不需要装 QGIS，它只做转发）
   - args：`<仓库路径>/qgis/live/mcp_server.py`
   注册后客户端应能列出 12 个 qgis_* 工具。

接入前建议先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token，共 6 项）；
它不需要 QGIS 也能跑。

## 工具清单

### 实时桥（12 个工具）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；视图级＝只改
显示状态、可逆、不落盘；写/执行类＝改变工程内容或运行算法，全部带
confirm=true 闸（confirm 只能在用户明确同意后由 Agent 填入）。

| 工具 | 作用 | 风险 |
|---|---|---|
| qgis_ping | 桥是否在线 | 只读 |
| qgis_discover | 发现当前工程接入方式 + 现场 API 清单（校准用） | 只读 |
| qgis_project_info | 当前工程概览（标题/路径/工程 CRS/图层数/接入模式） | 只读 |
| qgis_list_layers | 列图层（名称、数据源、CRS、显隐；实时模式经图层树带顺序与分组） | 只读 |
| qgis_list_layouts | 列打印布局名 | 只读 |
| qgis_list_fields | 列某矢量图层的字段（名称、类型、长度） | 只读 |
| qgis_export_map_image | 导出地图/布局为图片到指定路径（以文件真落盘且字节>0 为准） | 只读出文件 |
| qgis_set_layer_visible | 设置图层显隐 | 视图级 |
| qgis_zoom_to_layer | 画布缩放到图层范围；无画布时报 NOT_SUPPORTED 并附范围 | 视图级 |
| qgis_add_layer_from_path | 按路径加载图层并加入工程（须 confirm=true） | **写** |
| qgis_run_processing | 运行 Processing 算法，只接受算法 id＋参数 JSON（须 confirm=true） | **执行** |
| qgis_save_project | 保存当前工程（须 confirm=true） | **写** |

### 无头桥（3 个动作）

`preflight`（只读）、`backup`（只读原件，生成副本）、`inspect`（只读，
操作的是临时副本）。无头桥不包含任何写业务动作。

## 安全模型

- **仅本机**：实时桥只监听 127.0.0.1，不对外暴露；每次启动生成随机 token，
  请求必须带对 token 才执行，token 经本地文件在桥与 MCP 服务端之间传递。
- **写/执行操作 confirm 闸**：加图层、运行 Processing 算法、保存工程，
  缺 `confirm=true` 一律拒绝执行；confirm 只能在用户明确同意后填入。
- **没有任意代码执行**：run_processing 只传算法 id 与参数对象，不提供
  exec/eval 式工具；算法与参数在执行前应由用户复核。
- **无头模式只操作副本**：inspect 先复制到临时目录再打开/解析；backup 只生成
  新副本、从不覆盖；任何写需求都先 backup、只改工作副本，原件零写入。
- **如实报错纪律**：调不通的工具返回结构化错误并附现场方法清单，配套文档明确
  要求 Agent 如实回报，不许把失败粉饰成成功；报错即停，不许反复试探。

## 状态声明（请先读这一段）

- 无头桥：已在无 QGIS 的环境验证脚本语法、backup 的真实复制 + sha256、
  报错 JSON 与退出码；inspect 的纯解析策略已用自造的 .qgs/.qgz 样本工程
  实测（图层/数据源/CRS/图层树/布局均可正确盘点）；QgsApplication 策略与
  probe 的实机路径待使用者校准。
- 实时桥：已验证端到端协议层（`live/selftest.py` 6/6 PASS：握手、12 工具清单、
  ping 转发、discover 结构化回报、保存闸门、错误 token 拒绝）。
  **但实时模式尚未在真实 QGIS 上完成校准**：当前工程的注入方式、图层树显隐
  API 的确切名称、Qt 主线程调度策略是否稳定、Processing 与布局导出的真实
  签名都因版本而异，桥内采用多策略尝试 + 命中策略回报（via 字段）的实验性
  实现。首次实机使用必须按 [docs/CALIBRATION.md](docs/CALIBRATION.md) 的顺序
  逐项校准（先 discover 钉死实时接入策略，写/执行类工具只在工程副本上验证）。
- PyQGIS 不同版本的 API 命名有差异，桥接脚本会把命中的策略记进输出
  （`mode` / `opened_via` / `via` / `dispatch`），校准后请据实收紧并注明实机版本。

## 环境要求

- QGIS 3.x（建议 LTR 版本）；无头纯解析策略不需要装 QGIS。
- Python 3.x（MCP 服务端与无头桥）；实时桥使用 QGIS 自带的嵌入式 Python。
- 任一支持 stdio 的 MCP 客户端 / AI Agent（实时桥）；无头桥只需要能执行脚本的 Agent。
- QGIS 本身是自由软件（GPL），请从 qgis.org 获取正版安装。

## 目录结构

```
gis-agent-bridges/qgis/
├── README.md               本文件
├── SKILL.md                无头桥操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md              版本演进、待实机校准清单、后续候选
├── docs/
│   └── CALIBRATION.md      实机校准指南（顺序、验收标准、回报格式、红线）
├── scripts/
│   ├── qgis_bridge.py      无头桥脚本（preflight / backup / inspect，单行 JSON 输出）
│   └── probe_api.py        校准探针，输出本机 PyQGIS 的真实方法清单
└── live/
    ├── inapp_bridge.py     QGIS 应用内桥（localhost 服务，单文件可 exec）
    ├── mcp_server.py       MCP 服务端（stdio 转发，纯标准库）
    ├── selftest.py         实时桥一键自检（无 QGIS 环境可跑协议层）
    └── LIVE.md             实时桥使用说明（启动、工具清单与风险等级、纪律）
```

## 免责声明

本项目是独立的第三方开源工具，与 QGIS 项目及其社区没有任何隶属、授权或
合作关系；QGIS 等名称与商标归其权利方所有，本项目仅为互操作目的提及。
本工具按现状提供，不附带任何明示或默示担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
