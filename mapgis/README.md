# mapgis-bridge (probe-first, v0.1)

> **English** — mapgis-bridge is the MapGIS member of a GIS agent-bridge
> family. **It is exploratory and unverified.** MapGIS (Zondy Cyber / 中地数码)
> states that its MapGIS Objects SDK ships C++/Java/Python developer
> resources, but no public, authoritative documentation of the Python
> binding — module name, install layout, entry points — could be obtained,
> and it is **unknown whether MapGIS Desktop exposes any "current session"
> interface at all**. So this package deliberately contains **no live bridge
> and no claimed API**: it ships a rigorous environment probe plus a headless
> skeleton. The probe's JSON output is the evidence base for deciding whether
> — and how — a real bridge can be built. See the honesty statement below.

让 AI Agent 以受控、可审计的方式接入 MapGIS 工程的桥接工具（系列合集之一）。
但 MapGIS 这一员目前处在**探针先行**阶段：先把"目标机器上到底有没有可用的
MapGIS Python 绑定、长什么样"查清楚，再谈桥接路线。本包 v0.1 只交付探针、
无头骨架和实时桥设计说明，**不包含任何假装能跑的实时接入代码**。

## ⚠️ 诚实声明（请先读这一段）

- **EXPLORATORY / UNVERIFIED**：本包未经任何装有 MapGIS 的真实机器验证。
- 厂商（中地数码）官方口径称 MapGIS Objects SDK 提供 C++、Java、Python
  三种开发资源，但 Python 绑定的模块名、安装位置、类与方法清单**没有公开
  权威文档可查**，本包的候选模块名清单是启发式的，试过才算数。
- **"应用内当前会话"接口是否存在，未经证实。** MapGIS Desktop 是否像
  Blender / iDesktopX 那样允许外部脚本附着到当前打开的工程，目前无证据。
  因此 `live/` 目录里只有设计说明和探针版 MCP 服务端，**没有 inapp_bridge**，
  任何人都不许把本包描述成"可实时操作 MapGIS"。
- 无头 `inspect` 只在探针证实 SDK 存在时做候选入口的有限试探；打不开就
  返回结构化 `NOT_SUPPORTED` 并附全部尝试记录，**绝不编造盘点结果**。

## 本包交付物

| 文件 | 内容 |
|---|---|
| `scripts/probe_mapgis.py` | **核心交付**：多策略环境探针（见下） |
| `scripts/mapgis_bridge.py` | 无头骨架三动作：preflight / backup / inspect |
| `live/mcp_server.py` | 纯标准库 stdio MCP 服务端，只暴露 3 个探针工具 |
| `live/selftest.py` | 协议自检（5 项），无 MapGIS 环境可跑 |
| `live/LIVE.md` | 实时桥三种候选路线的设计说明与各自待证实点 |
| `SKILL.md` | 探针先行的工作流手册（给执行 Agent 看） |
| `docs/CALIBRATION.md` | 实机探针执行单（顺序、验收标准、红线） |
| `ROADMAP.md` | 探针结果 → 路线决策门 |

## 探针做什么

`scripts/probe_mapgis.py` 在目标机器上依次执行，全过程只读：

1. 读取环境变量线索：`MAPGIS_HOME` / `ZONDY_HOME` / `MAPGIS_PATH` / `ZONDY_PATH`；
2. 启发式扫描 Program Files 等根目录下名称含 mapgis / zondy 的安装目录；
3. 对候选模块名（`mapgis`、`MapGIS`、`mapgis_objects`、`zondy`、`zgis` 等
   12 个）逐个 import 试探，**逐个记录成败与原始报错**；
4. 任一模块导入成功：枚举其顶层符号与每个类的公开方法清单写入 JSON。

输出为单行 JSON。全部失败时输出结构化 `MAPGIS_PYTHON_NOT_FOUND` 加完整
尝试清单（退出码 1）；找到时退出码 0。**这份 JSON 就是下一步立项的依据**：
请完整回传给维护者，不要删减、不要加结论性粉饰。

## 快速上手

```bash
# 1) 在装有 MapGIS 的机器上先跑探针（任意 Python 3；若 MapGIS 自带 Python 解释器，优先用它再跑一遍）
python scripts/probe_mapgis.py > probe-result.json

# 2) 无头骨架
python scripts/mapgis_bridge.py preflight
python scripts/mapgis_bridge.py backup  <某个 .MPJ 工程文件>
python scripts/mapgis_bridge.py inspect <某个 .MPJ 工程文件>

# 3) MCP 探针服务端自检与注册
python live/selftest.py
# 在你的 AI Agent / MCP 客户端中注册：
#   command: 任意 Python 3 解释器
#   args:    <仓库路径>/live/mcp_server.py
# 注册后应能列出 3 个 mapgis_* 工具（ping / discover / probe_environment）。
```

给执行 Agent 的第一份任务可以这样下达（结果式表述）：

> 读 `<仓库路径>/SKILL.md` 并严格按它执行。目标结果：
> (1) 运行 probe_mapgis.py 并完整回传 JSON 原文；
> (2) 若探针命中模块，再对工程文件 `<你的某个 .MPJ 路径>` 先 backup 再 inspect，
> 回报两份 JSON 原文。探针未命中就停在第 (1) 步，不许自行安装任何包、
> 不许换环境反复试探、不要改动与本任务无关的既有项目环境。

## 工具清单

### 无头骨架（3 个动作）

| 动作 | 说明 | 状态 |
|---|---|---|
| `preflight` | 即探针：环境是否可用完全取决于探针结论 | 已实现 |
| `backup` | 复制 .MPJ 及同名数据文件，带时间戳并回报 sha256 | 已实现（纯标准库） |
| `inspect` | 探针证实 SDK 存在后，按候选 API 多策略尝试打开工程；失败返回 `NOT_SUPPORTED` | 骨架，待实机收紧 |

### MCP 探针工具（3 个）

| 工具 | 作用 | 鉴权 |
|---|---|---|
| `mapgis_ping` | 服务端健康检查 | 无 |
| `mapgis_discover` | 探针结论摘要（是否找到绑定、命中模块、安装目录） | 须带 token |
| `mapgis_probe_environment` | 探针全量 JSON（立项依据） | 须带 token |

token 约定与本系列其他桥一致：服务端启动时在 `~/.mapgis-bridge.token`
生成/读取 token，受保护工具调用时须在 arguments 中带对。

## 安全模型

- **探针只读**：不写文件、不改环境、不装包；导入试探的失败原样记录。
- **原件只读**：backup 只生成新副本、从不覆盖；inspect 不写工程内容。
- **如实报错纪律**：找不到就报 `MAPGIS_PYTHON_NOT_FOUND`，打不开就报
  `NOT_SUPPORTED` 并附尝试清单；不许把失败粉饰成成功，不许编造 API 或盘点结果。
- **token 纪律**：探针全量结果可能暴露本机目录结构，只经带 token 的工具调用获取，
  不要把 token 或探针 JSON 发给无关方。

## 目录结构

```
mapgis/
├── README.md               本文件
├── SKILL.md                探针先行工作流手册
├── ROADMAP.md              探针结果 → 路线决策门
├── docs/
│   └── CALIBRATION.md      实机探针执行单
├── scripts/
│   ├── probe_mapgis.py     环境探针（核心交付）
│   └── mapgis_bridge.py    无头骨架（preflight / backup / inspect）
└── live/
    ├── LIVE.md             实时桥候选路线设计说明（无应用内桥，刻意为之）
    ├── mcp_server.py       探针版 MCP 服务端（3 个工具）
    └── selftest.py         协议自检（5 项）
```

## 环境要求

- 探针与 MCP 服务端：Python 3.x、纯标准库，无第三方依赖。
- 目标机器（探针执行地）：装有 MapGIS 10 系列桌面与合法许可的 Windows 机器
  （本项目不提供、不绕过任何许可机制）；若 MapGIS 自带 Python 解释器，
  用它再跑一遍探针，两个解释器的结果都要回传。

## 免责声明

本项目是独立的第三方开源工具，与中地数码（Zondy Cyber）没有任何隶属、
授权或合作关系；MapGIS、Zondy 等名称与商标归其权利方所有，本项目仅为
互操作目的提及。本工具按现状提供，不附带任何明示或默示担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
