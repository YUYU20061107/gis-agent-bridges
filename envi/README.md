# envi-bridge（gis-agent-bridges 系列）

> **English** — envi-bridge is the headless-only member of the gis-agent-bridges
> family: it lets an AI agent work with ENVI raster data **without attaching to
> a running ENVI GUI** — because ENVI offers no officially supported way to
> attach to an already-open session. It has two layers: (1) a pure-Python
> ENVI `.hdr` parser that inventories raster files on any machine, with no ENVI
> installation and no license; and (2) an MCP server that, when the IDL–Python
> bridge (`idlpy`) is available, lazily starts a headless ENVI session
> (`IDL.ENVI(HEADLESS=1)`) and runs ENVITask jobs behind an explicit
> confirmation gate. **Headless only, by design and by necessity — see
> `live/HEADLESS.md`.**

让 AI Agent 以受控、可审计的方式使用 ENVI 栅格数据与 ENVITask 算法的无头桥。
ENVI 的本体 API 是 IDL 的 ENVITask 体系，Python 侧经 `idlpy` 桥驱动；
与本系列其他桥不同，ENVI **没有**官方支持的"附着到用户已打开的那个 ENVI
窗口"的通道，所以本包只做无头版，不假装能实时接入 GUI。

## 项目由来

这两年，CAD、Blender 等工科软件陆续出现了让 AI Agent 直接接入、操作当前工程的服务。GIS 与遥感这边还基本是空白——就想为我们 GIS/遥感也加一个。ENVI 是遥感影像处理的老牌主力，自然要在系列里占一格；只是它的接入形态与桌面 GIS 不同：强项在无头批处理，会话附着则无路可走。本包把这两件事都讲明白，能做的做扎实，做不到的明说。

## 两种能力层

### 第一层：.hdr 纯 Python 盘点（不需要 ENVI）

ENVI 栅格的 `.hdr` 头文件是纯文本：samples/lines/bands、data type、
interleave、map info、band names、wavelength 都在里面。桥内置一个按
花括号深度切分的 `.hdr` 解析器，**任何装有 Python 3 的机器**都能对
ENVI 栅格做盘点与完整性核对（期望字节数 vs 实际文件大小），不碰许可。

### 第二层：idlpy 无头会话（需要 ENVI + IDL 许可）

`live/mcp_server.py` 在宿主 Python 里惰性 `import idlpy`，首次需要时
启动 `IDL.ENVI(HEADLESS=1)` 会话，经 ENVITask 执行任务。会话只试启一次：
失败即如实记因（`ENVI_NOT_AVAILABLE`），不反复重试、不假装执行。

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│  你的 AI Agent / MCP 客户端（7 个 envi_* 工具）                     │
└──────────────────────────┬───────────────────────────────────────┘
                           │ MCP (stdio)
┌──────────────────────────▼───────────────────────────────────────┐
│  live/mcp_server.py（纯 Python 标准库）                            │
│   ├─ .hdr 解析（内联实现，无 ENVI 可用）                            │
│   └─ 惰性 idlpy 会话 → IDL.ENVI(HEADLESS=1) → ENVITask            │
└──────────────────────────────────────────────────────────────────┘

无头脚本：Agent → scripts/envi_bridge.py（preflight / inventory / backup）
         → .hdr 解析与文件复制；probe_api.py 做版本校准
```

注意：**没有 inapp_bridge.py**。其他桥的应用内桥依赖宿主软件提供
"当前会话"句柄，ENVI 对第三方 Python 没有这个入口（详见 `live/HEADLESS.md`）。

## 快速上手

### 只盘点（无 ENVI 环境）

```
<python3> scripts/envi_bridge.py inventory <目录或.hdr或数据文件>
<python3> scripts/envi_bridge.py backup <栅格文件或.hdr>
```

验收：JSON 里 samples/lines/bands 与 ENVI 里打开看到的一致（或与数据提供方
文档一致）；`size_matches=true` 表示数据文件字节数与头文件描述吻合。

### MCP 服务端

在你的 AI Agent / MCP 客户端配置中注册：

- command：装有 idlpy 的 Python（没有 idlpy 也能注册，盘点工具照常工作）
- args：`<仓库路径>/envi/live/mcp_server.py`
- 可选环境变量 `ENVI_BRIDGE_TOKEN`：设置后 tools/call 须在
  `params._meta.token` 带对 token，否则被 `BAD_TOKEN` 拒绝。

接入前先跑 `live/selftest.py` 自检协议层（initialize / tools-list /
ping / discover / run_task 闸门 / 错误 token，共 6 项）。

## 工具清单

风险等级：只读＝无副作用；写类＝会生成新数据/文件，全部带 confirm=true 闸
（confirm 只能在用户明确同意后由 Agent 填入）。

### 无头脚本（3 个动作）

| 动作 | 说明 |
|---|---|
| `preflight` | 预检：.hdr 解析能力、idlpy 可导入性、ENVI/IDL 安装线索 |
| `inventory` | 盘点：纯 Python 解析 .hdr（单个文件或整目录），含大小核对 |
| `backup` | 备份：复制栅格文件对（数据 + .hdr）为时间戳副本并回报 sha256 |

### MCP 工具（7 个）

| 工具 | 作用 | 风险 |
|---|---|---|
| envi_ping | 无头桥在线检查 | 只读 |
| envi_discover | 本机 idlpy/ENVI 可用性与安装线索（校准用） | 只读 |
| envi_raster_info | 栅格盘点：优先 .hdr 解析（`source=hdr-parse`）；verify 时可用 ENVI 打开核对（`source=envi`） | 只读 |
| envi_list_tasks | 列 ENVITask 任务名抽样；无 ENVI 时返回 `ENVI_NOT_AVAILABLE` | 只读 |
| envi_describe_task | 读某 ENVITask 的参数 schema（不执行）；无 ENVI 时结构化返回 | 只读 |
| envi_run_task | 经 ENVITask 执行任务，须 confirm=true；无 ENVI 时返回 `ENVI_NOT_AVAILABLE`、绝不假装执行 | **写** |
| envi_export_raster_subset | 导出栅格子集到新文件，须 confirm=true；仅 .hdr 模式返回 `NOT_SUPPORTED_IN_HDR_MODE` | **写** |

## 安全模型

- **confirm 闸**：run_task / export 缺 `confirm=true` 一律拒绝；confirm 只能由用户明确同意后填入。
- **可选 token 闸**：设置 `ENVI_BRIDGE_TOKEN` 后，无正确 token 的 tools/call 一律 `BAD_TOKEN`。
- **原件只读**：inventory 只读文件；backup 只生成新副本、从不覆盖；run_task 的输入栅格不被就地修改（任务输出路径由参数指定，校准指南要求指向副本目录）。
- **如实报错纪律**：没有 ENVI 就报 `ENVI_NOT_AVAILABLE` 并停，不许拿 .hdr 盘点结果冒充任务执行结果；许可报错即停，不许反复试探。

## 状态声明（请先读这一段）

- .hdr 解析层：已在无 ENVI 的环境用自造样本实测（samples/lines/bands、
  波长、band names、map info、期望字节数与大小核对均正确）。
- MCP 协议层：`live/selftest.py` 6/6 PASS（握手、7 工具清单、ping、
  discover 结构化回报、run_task 闸门、错误 token 拒绝）。
- **idlpy 实机会话路径未验证**：本包开发环境没有 ENVI/IDL，ENVITask 的
  任务名枚举、参数读写、Execute 与输出回收采用多策略尝试 + 命中策略
  回报（via 字段）的实验性实现。首次实机使用必须按
  [docs/CALIBRATION.md](docs/CALIBRATION.md) 的顺序校准。

## 环境要求

- 盘点层：任意 Python 3，无其他依赖。
- 任务层：ENVI + IDL 许可、与之配套的 idlpy（随 IDL/ENVI 安装或官方桥包），
  在注册 MCP 时把 command 指向装有 idlpy 的解释器。
- 任一支持 stdio 的 MCP 客户端 / AI Agent。
- 一份你自己合法持有的 ENVI/IDL 许可（本项目不提供、不绕过任何许可机制）。

## 目录结构

```
envi/
├── README.md            本文件
├── SKILL.md             操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md           版本演进、实时版（IDL 驻留扩展）评估、待校准清单
├── docs/
│   └── CALIBRATION.md   实机校准指南（顺序、验收标准、回报格式、红线）
├── scripts/
│   ├── envi_bridge.py   无头脚本（preflight / inventory / backup，单行 JSON 输出）
│   └── probe_api.py     校准探针，输出 idlpy 可用性、ENVI 版本与 ENVITask 抽样
└── live/
    ├── mcp_server.py    MCP 服务端（stdio，纯标准库；工具在本进程内执行）
    ├── selftest.py      一键自检（无 ENVI 环境可跑协议层 + 盘点层）
    └── HEADLESS.md      为什么本包没有实时桥：会话模型说明（代 LIVE.md）
```

## 免责声明

本项目是独立的第三方开源工具，与 NV5 Geospatial Solutions（原 L3Harris /
Exelis）没有任何隶属、授权或合作关系；ENVI、IDL 等名称与商标归其权利方
所有，本项目仅为互操作目的提及。使用本工具需要你自备正版 ENVI/IDL 软件
与许可，并自行对操作结果负责。本工具按现状提供，不附带任何明示或默示
担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。

v0.2（2026-10-24）：selftest 改后台线程+队列读行（弃 select，修 Windows 管道问题）；新增 scripts/verify_project.py（.hdr 文件对盘点 + 伴生文件完整性 + --copy-to 副本重盘）与 ENGINEERING-PLAYBOOK.md；token 仍只用环境变量 ENVI_BRIDGE_TOKEN（无 token 文件）；工具清单（7 个）、confirm 闸与 BAD_TOKEN 语义不变，仍仅无头，idlpy 任务层未做实机校准。
