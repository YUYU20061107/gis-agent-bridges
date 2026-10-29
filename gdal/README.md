# GDAL/OGR 工具桥（gis-agent-bridges / gdal）

> **English** — This package is a *headless tool* bridge for
> the GDAL/OGR command-line utilities (`gdalinfo`, `ogrinfo`,
> `gdal_translate`, `ogr2ogr`). It offers **no passthrough of
> raw GDAL options**: reads use fixed templates
> (`gdalinfo -json`, `gdalinfo -stats -json`,
> `ogrinfo -so -al`), and conversions pick from a small format
> enum. Every subprocess runs with `GDAL_PAM_ENABLED=NO`, so
> read-only inspection never drops an `.aux.xml` sidecar next
> to your original file. Inputs must be local files (remote
> and `/vsi*` paths are refused); conversions only write new
> files and require `confirm=true`. **This is not an official
> GDAL / OSGeo component.** Its current evidence level is
> protocol-level self-check only: it has **not yet been
> calibrated against a real GDAL installation**.

让 AI Agent 用 GDAL 命令行四件套干最常见的三件事：看清
一个栅格/矢量文件到底是什么（驱动、尺寸、波段、图层、
字段、要素数），取一遍波段统计；在你确认之后，把文件
转换成另一种格式的新文件。它是 GIS 工作流里的“瑞士
军刀前置站”：任何文件进桌面 GIS 或处理流水线之前，先
用它验明正身。

## 定位声明（请先读这一段）

- **不是官方组件**：本包是 gis-agent-bridges 合集仓的社区
小桥，不是 GDAL 官方组件，与 GDAL / OSGeo 官方项目无
隶属关系。GDAL 本体的文档、发行与支持请走其官方渠道。
- **没有原始选项透传**：能发给 GDAL 的只有写死的模板
（见 `scripts/gdal_bridge.py`）：工具参数里没有、也不
接受任何 GDAL 选项串——没有 `-co`、没有 `-a_srs`、
没有重投影与裁剪。需要那些能力，请直接用你自己的
GDAL 命令行，或走本仓的处理型包（如 grass-gis）。
- **只读探查零副作用**：所有子进程强制
`GDAL_PAM_ENABLED=NO`。这意味着 `gdalinfo -stats` 这类
通常会在原件旁写 `.aux.xml` 的操作，在本桥下不会留下
任何伴生文件——探查就是探查，不动原件一个字节。
- **转换只写新文件**：输出必须尚不存在、扩展名须与目标
格式匹配，绝不覆盖；格式只有小枚举（栅格 GTiff/PNG/
JPEG，矢量 GeoJSON/GPKG）。

## 入口

### MCP 服务端（live/）

纯标准库 stdio MCP 服务端，7 个工具，自检脚本
`live/selftest.py`。运行说明、token、环境变量与故障排查
见 [`live/HEADLESS.md`](live/HEADLESS.md)。

| 工具 | 作用 | 风险 |
|---|---|---|
| gdal_ping | 桥是否在线、gdalinfo/ogrinfo 是否可用 | 只读 |
| gdal_discover | 环境发现：四件工具路径/版本、格式枚举、输入输出政策（校准用） | 只读 |
| gdal_raster_info | 固定 `gdalinfo -json` 模板探查栅格（驱动/尺寸/波段/变换/角点/投影） | 只读 |
| gdal_vector_info | 固定 `ogrinfo -so -al` 模板探查矢量（图层/几何/要素数/范围/字段） | 只读 |
| gdal_raster_stats | 固定 `gdalinfo -stats -json` 模板取波段 min/max/mean/stdDev | 只读 |
| gdal_convert_raster | 固定 `gdal_translate -of` 模板转栅格为新文件（GTiff/PNG/JPEG），须 confirm=true | 写新文件（confirm 闸） |
| gdal_convert_vector | 固定 `ogr2ogr -f` 模板转矢量为新文件（GeoJSON/GPKG），须 confirm=true | 写新文件（confirm 闸） |

### 命令行侧（scripts/）

| 文件 | 说明 |
|---|---|
| `scripts/gdal_bridge.py` | 路径/校验/调用库（服务端与探针共用，不单独执行） |
| `scripts/probe_api.py` | 环境探针：四件工具的路径、可用性、版本，输出单行 JSON |

操作手册见 `SKILL.md`。

## 架构

```
AI Agent / MCP 客户端
│ stdio（MCP 协议，_token 守卫常开）
▼
live/mcp_server.py（纯标准库，不监听任何网络端口）
│ 只拼固定模板；路径先过 gdal_bridge.py 校验
│ 子进程 env 强制 GDAL_PAM_ENABLED=NO
▼
gdalinfo / ogrinfo / gdal_translate / ogr2ogr（参数数组，不经 shell）
│
▼
你本机的栅格/矢量文件（探查只读；转换只写新文件）
```

## 快速上手

### 先跑协议自检（无需 GDAL）

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 15/15 PASS
```

自检用四个假二进制替身（经 `GDAL_BRIDGE_*` 环境变量注入）
验证 MCP 协议、解析、confirm 与 token 安全闸，并断言
子进程实际拿到的 `GDAL_PAM_ENABLED` 为 NO，不调用真实
GDAL，也不是实机校准。

### 接自己的 GDAL

```bash
python3 scripts/probe_api.py
```

探针四件工具全 `available=true` 后，再把
`live/mcp_server.py` 注册进 MCP 客户端；四件工具不在
客户端进程的 PATH 里时，用 `GDAL_BRIDGE_GDALINFO` 等
四个变量逐件写进客户端配置的 `env` 段指定完整路径，
不能指望客户端继承另一个终端的 `export`。

### token 与 confirm：两道闸先说清

- **token**：本包与桌面包不同，**服务端不会替调用方自动
附带 `_token`**。每一次 `tools/call` 都必须在
`arguments` 里带 `_token`，否则 `BAD_TOKEN`。来源二选
一：`GDAL_BRIDGE_TOKEN` 环境变量（优先），或 token
文件 `~/.gdal-agent-bridge.token`（首次启动两处都没有
时服务端生成随机 token 写入，0600）。细节见
[`live/HEADLESS.md`](live/HEADLESS.md)。
- **confirm**：两个 convert 工具缺 `confirm=true` 一律
`CONFIRM_REQUIRED`，且在启动 GDAL 之前就拒绝。
confirm 只能在用户明确同意后填入。

## 安全模型

1. **模板写死**：五条调用模板（三种探查＋两种转换）在
代码里固定；工具参数里没有、也不接受任何 GDAL 选项
串，无 `-co` 等创建选项透传。
2. **输入只许本地文件**：http(s) 与 `/vsi*` 路径在调用
二进制前一律 `REMOTE_PATH_REJECTED`；路径不存在
`PATH_NOT_FOUND`。本桥不做网络数据集探查。
3. **PAM 强制关闭**：子进程环境恒含
`GDAL_PAM_ENABLED=NO`，且不提供放行开关——调用方
环境里设了 YES 也会被覆盖。只读探查对原件零副作用。
4. **转换只写新文件**：输出必须不存在（`OUTPUT_EXISTS`
在调用前拒绝）、扩展名须与格式枚举匹配、父目录须
已存在；落盘后桥复核文件真实存在才报成功。
5. **confirm 闸**：写类工具缺 confirm=true 在启动 GDAL
前拒绝；闸的判定不依赖 GDAL 是否可用。
6. **token 守卫常开**：无 token 或错 token 的 tools/call
一律 `BAD_TOKEN` 拒绝；服务端走 stdio，不监听网络
端口。转换类调用记入
`~/.gdal-agent-bridge/runs.jsonl`（不记 token）。

## 状态声明

- **证据级别：协议自检（未实机校准）**。按本仓三级证据
口径，本包目前只有协议自检级证据：开发机（VM，
Python 3.12.3，2026-10-29）无 GDAL 环境，
`live/selftest.py` 用四个假二进制替身回放罐装输出，
实跑结果 **15/15 PASS**（initialize、工具清单 7 个、
ping/discover、栅格信息解析且 PAM 环境断言成立、矢量
图层解析、波段统计解析、无 token 与错 token 拒绝、
缺 confirm 在执行前被拒且二进制未被调用、栅格转换
正例且 argv 无 -co、拒绝覆盖、枚举外格式被拒、远程
路径在调用前被拒、矢量转换正例）。
- 同机 `scripts/probe_api.py` 实跑如实回报四件工具全部
`available: false`、退出码 1——GDAL 都没有，自然谈不上
探查或转换过任何真实文件。
- **不要把自检通过当作已在真实 GDAL 上验证**：
`gdalinfo -json` 在老版本 GDAL 上的可用性、ogrinfo
文本形态随驱动的差异、GPKG 等数据集型输出的目录语义，
须按 `docs/CALIBRATION.md` 在真实 GDAL 上逐项校准后
才成立。

## 环境要求

- Python 3.x（服务端与脚本只用标准库，无第三方依赖，
无 requirements）。
- GDAL 命令行工具（gdalinfo / ogrinfo / gdal_translate /
ogr2ogr 同版本成套，以实机校准为准），四件都在 PATH
中，或用 `GDAL_BRIDGE_*` 环境变量逐件指定。

## 目录结构

```
gdal/
├── README.md / SKILL.md / ROADMAP.md / ENGINEERING-PLAYBOOK.md
├── LICENSE /.gitignore
├── live/
│ ├── mcp_server.py # stdio MCP 服务端（7 个工具，token 守卫常开）
│ ├── HEADLESS.md # 无头形态、token、confirm、环境变量与故障排查
│ └── selftest.py # 协议自检（四假二进制替身，15 项）
├── scripts/
│ ├── gdal_bridge.py # 路径/校验/调用库（固定五模板，PAM 强制关）
│ └── probe_api.py # 环境探针（只读）
├── docs/
│ └── CALIBRATION.md # 实机校准工单（真实 GDAL 环境）
└── examples/
├── mcp-client-config.json
└── prompts.md
```

## 免责声明

本包按现状提供。探查结果忠实于 GDAL 自身的解析：文件
本身损坏或驱动识别有误时，桥回传的是 GDAL 的结论或
报错，不代表文件内容的业务正确性。转换是格式层面的
直转，不做重投影、重采样或字段映射；转换结果用于正式
交付前，请在目标软件里复核。

## License

MIT，见 `LICENSE`。
