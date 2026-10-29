# GRASS GIS 无头桥（gis-agent-bridges / grass-gis）

> **English** — This package is a *headless batch* bridge for
> GRASS GIS. GRASS has no officially supported channel for
> attaching to an already-open GUI session, so this bridge runs
> `grass <mapset> --exec <module>` as a subprocess. It offers
> **no arbitrary module execution**: the only callable modules
> are fixed templates (`g.list`, `r.info`, `v.out.ogr`, and
> three run jobs — `r.slope.aspect`, `r.relief`, `r.resample`).
> Processing tools never pass `--overwrite`, so results can
> only land as new maps; exports only write new files. Write /
> execute tools require `confirm=true`. **This is not an
> official GRASS GIS or OSGeo component.** Its current
> evidence level is protocol-level self-check only: it has
> **not yet been calibrated against a real GRASS GIS
> installation**.

让 AI Agent 以无头批处理方式使用 GRASS GIS 的处理能力：
先看清一个 location 里有什么图层、某张栅格的范围与分辨率，
再按三个固定作业模板（坡度坡向、晕渲、最近邻重采样）跑
处理，结果只能落成新图层；矢量图层可以导出成 GeoJSON
新文件。没有 GRASS 的机器上依赖 GRASS 的工具如实报不可用，
绝不假装执行过。

## 定位声明（请先读这一段）

- **不是官方组件**：本包是 gis-agent-bridges 合集仓的社区
小桥，不是 GRASS GIS 官方组件，与 GRASS GIS / OSGeo
官方项目无隶属关系。GRASS 本体的文档、发行与支持请走
其官方渠道。
- **只有无头形态**：GRASS 没有官方支持的 GUI 会话附着
通道（与本仓 envi 包同理）。本桥跑的是你本机安装的
GRASS 批处理入口，不连接任何已打开的 GRASS 窗口；GUI
里正在编辑的未保存状态，本桥看不见也不碰。
- **没有任意模块执行入口**：能调的模块只有写死的模板
（见 `scripts/grass_bridge.py`）：模块名、参数名固定，
调用方只能提供经校验的值。想跑模板之外的 GRASS 模块，
请直接用你自己的 GRASS，不要指望本桥放行。
- **原件保护（副本原则的进程内形态）**：处理作业绝不传
`--overwrite`，输出图层名与已有图层重名时 GRASS 自己
会报错拒绝，桥原样回传；导出只写不存在的新文件。这样
保证 Agent 的每一次处理都不动既有图层与既有文件。

## 入口

### MCP 服务端（live/）

纯标准库 stdio MCP 服务端，7 个工具，自检脚本
`live/selftest.py`。运行说明、token、环境变量与故障排查
见 [`live/HEADLESS.md`](live/HEADLESS.md)。

| 工具 | 作用 | 风险 |
|---|---|---|
| grass_ping | 桥是否在线、grass 是否可用与版本 | 只读 |
| grass_discover | 环境发现：grass 可用性、GIS 数据库与 location 清单、固定作业枚举（校准用） | 只读 |
| grass_location_info | 某 location 的投影与默认区域（纯 Python 解析 PROJ_INFO/WIND，不启动 GRASS） | 只读 |
| grass_list_maps | 固定 `g.list` 模板列某 mapset 的图层名 | 只读 |
| grass_raster_info | 固定 `r.info -g` 模板取栅格范围/分辨率/行列数 | 只读 |
| grass_run_module | 三个固定作业模板之一（slope_aspect / hillshade / resample_nearest），须 confirm=true，输出只能是新图层 | 执行（confirm 闸） |
| grass_export_vector | 固定 `v.out.ogr` 模板把矢量图层导出为 GeoJSON 新文件，须 confirm=true，已存在拒绝覆盖 | 写新文件（confirm 闸） |

### 命令行侧（scripts/）

| 文件 | 说明 |
|---|---|
| `scripts/grass_bridge.py` | 路径/校验/调用库（服务端与探针共用，不单独执行） |
| `scripts/probe_api.py` | 环境探针：grass 版本、gisdbase 与 location 清单，输出单行 JSON |

操作手册见 `SKILL.md`。

## 架构

```
AI Agent / MCP 客户端
│ stdio（MCP 协议，_token 守卫常开）
▼
live/mcp_server.py（纯标准库，不监听任何网络端口）
│ 只拼固定模板；名字/路径先过 grass_bridge.py 校验
▼
grass 子进程（参数数组，不经 shell；<mapset> --exec <固定模块>）
│
▼
你本机的 GRASS GIS 与 GRASS 数据库（gisdbase 只从环境变量读）
```

## 快速上手

### 先跑协议自检（无需 GRASS）

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 15/15 PASS
```

自检用假 grass 替身与纯文件搭的假 location，只验证 MCP
协议、参数校验、confirm 与 token 安全闸，不启动真实
GRASS，也不是实机校准。

### 接自己的 GRASS

```bash
export GRASS_BRIDGE_GISDBASE=<GRASS 数据库根目录>
python3 scripts/probe_api.py
```

探针 `ready=true` 后，再把 `live/mcp_server.py` 注册进
MCP 客户端。若客户端负责拉起服务端，`GRASS_BRIDGE_GISDBASE`
必须同样写进客户端配置的 `env` 段；只在另一个终端
`export` 不会被 GUI 客户端自动继承。

### token 与 confirm：两道闸先说清

- **token**：本包与桌面包不同，**服务端不会替调用方自动
附带 `_token`**。每一次 `tools/call` 都必须在
`arguments` 里带 `_token`，否则 `BAD_TOKEN`。来源二选
一：`GRASS_BRIDGE_TOKEN` 环境变量（优先），或 token
文件 `~/.grass-agent-bridge.token`（首次启动两处都没有
时服务端生成随机 token 写入，0600）。细节见
[`live/HEADLESS.md`](live/HEADLESS.md)。
- **confirm**：`grass_run_module` 与 `grass_export_vector`
缺 `confirm=true` 一律 `CONFIRM_REQUIRED`，且在启动
GRASS 之前就拒绝。confirm 只能在用户明确同意后填入。

## 安全模型

1. **模板写死**：模块与参数名在代码里固定为六条模板
（g.list / r.info / v.out.ogr 与三个 run 作业），工具
参数里没有、也不接受任何模块名或原始参数串。
2. **名字与路径校验**：图层名只许 `[A-Za-z0-9_.]`（可带
一个 `@mapset`）；location/mapset 只许单个路径分量，
拼出的真实路径必须落在 gisdbase（只从环境变量读）
之内，防路径穿越。
3. **子进程参数数组**：grass 以 argv 数组调用，不经
shell；模块参数以 `key=value` 单元素传入，值先经
校验。
4. **永不覆盖**：绝不传 `--overwrite`；输出图层只能是
新名（不许带 @mapset）；导出文件必须不存在且以
`.geojson` 结尾，设置了 `GRASS_BRIDGE_EXPORT_DIR`
时必须落在其内。
5. **confirm 闸**：执行/写类工具缺 confirm=true 在启动
GRASS 前拒绝；闸的判定不依赖 GRASS 是否可用（无
GRASS 的机器上同样先过闸）。
6. **token 守卫常开**：无 token 或错 token 的 tools/call
一律 `BAD_TOKEN` 拒绝；服务端走 stdio，不监听网络
端口。写/执行类调用记入
`~/.grass-agent-bridge/runs.jsonl`（不记 token）。

## 状态声明

- **证据级别：协议自检（未实机校准）**。按本仓三级证据
口径，本包目前只有协议自检级证据：开发机（VM，
Python 3.12.3，2026-10-29）无 GRASS GIS 环境，
`live/selftest.py` 用假 grass 替身回放罐装输出、假
location 只用文件搭出，实跑结果 **15/15 PASS**
（initialize、工具清单 7 个、ping/discover、location
文件解析、列图层与栅格信息正例、无 token 与错 token
拒绝、缺 confirm 在执行前被拒且替身未被调用、作业
正例且 argv 无 --overwrite、枚举外作业被拒、导出闸
与落盘、拒绝覆盖、非法图层名在执行前被拒）。
- 同机 `scripts/probe_api.py` 实跑如实回报
`grass_available: false`、退出码 1——GRASS 都没有，
自然谈不上跑通任何模块。
- **不要把自检通过当作已在真实 GRASS 上验证**：六条模板
在真实 GRASS 8.x 上的实际行为（g.list 输出形态、
r.info -g 键集、--exec 的锁与区域语义、v.out.ogr 的
GeoJSON 驱动可用性）须按 `docs/CALIBRATION.md` 在
真实 GRASS GIS 上逐项校准后才成立。

## 环境要求

- Python 3.x（服务端与脚本只用标准库，无第三方依赖，
无 requirements）。
- GRASS GIS 安装（版本以实机校准为准），`grass` 启动器
在 PATH 中（或用 `GRASS_BRIDGE_BIN` 指定）；一个已有
的 GRASS 数据库（gisdbase），桥不会替你新建 location
或 mapset。

## 目录结构

```
grass-gis/
├── README.md / SKILL.md / ROADMAP.md / ENGINEERING-PLAYBOOK.md
├── LICENSE /.gitignore
├── live/
│ ├── mcp_server.py # stdio MCP 服务端（7 个工具，token 守卫常开）
│ ├── HEADLESS.md # 无头形态、token、confirm、环境变量与故障排查
│ └── selftest.py # 协议自检（假 grass 替身＋假 location，15 项）
├── scripts/
│ ├── grass_bridge.py # 路径/校验/调用库（固定六模板）
│ └── probe_api.py # 环境探针（只读）
├── docs/
│ └── CALIBRATION.md # 实机校准工单（真实 GRASS GIS 环境）
└── examples/
├── mcp-client-config.json
└── prompts.md
```

## 免责声明

本包按现状提供。处理结果的正确性取决于 GRASS 版本、区域
设置与输入数据质量；桥只保证“按固定模板如实调用并回传”，
不保证算法结果的业务正确性。作业在目标 mapset 里新建
图层，运行前请确认 mapset 是可以写的工作区副本，不要直接
在原始数据 mapset 上跑。

## License

MIT，见 `LICENSE`。
