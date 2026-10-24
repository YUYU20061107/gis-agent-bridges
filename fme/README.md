# FME 无头 Runner（gis-agent-bridges / fme）

> **English** — This package lets an AI agent run FME workspace files (`.fmw`)
> headlessly on a local machine, through Safe Software's official Python API
> (`fmeobjects.FMEWorkspaceRunner`). FME has no "current session" API, so —
> unlike the live GUI bridges elsewhere in this collection — this package is a
> *local headless runner* only: it inventories `.fmw` files, parses their text
> for datasets and transformers, backs them up, and runs them behind an explicit
> confirmation gate with a run journal. **For server-side scenarios, Safe
> Software already ships an official MCP Server for FME Flow — use that one.**
> This package only fills the narrow local gap: running a `.fmw` file directly
> under a desktop FME license, from an AI agent, with guardrails.

让 AI Agent 在本地无头运行 FME workspace 文件（*.fmw）的受控 runner：盘点、
解析、备份，以及带 confirm 闸与运行日志的执行。FME 没有"当前会话"接口，
本包**不接入任何 FME 图形界面会话**，与本合集里其他软件的实时桥定位不同。

## 定位声明（请先读这一段）

- **服务器场景请用官方**：Safe Software 官方已推出 FME Flow 的 MCP Server
  （服务器侧、带官方权限治理）。凡是发布、调度、多人协作、权限审计类需求，
  直接用官方 Flow MCP，本包不与之竞争。
- **本包只补一条窄缝**：在本机桌面版 FME 授权下，让 AI Agent 直接跑一个
  .fmw 文件——盘点它、解析它、先备份、经用户确认后运行、留运行日志。
  定位互补，不是官方方案的替代品。
- **诚实边界**：`workspace_info` 是对 .fmw 文本的尽力解析（标注
  `mode=file-parse`、`complete=false`），宏不展开、INCLUDE 不跟随，
  可能不完整；拿不到的字段如实留空，不猜。

## 两种入口

### 命令行桥（scripts/）

| 动作 | 说明 |
|---|---|
| `preflight` | 环境预检：多策略探测 FME 安装与 fmeobjects 可导入性 |
| `scan` | 扫描目录，列出 .fmw 清单（路径、大小、修改时间） |
| `info` | 解析 .fmw 文本：源/目标数据集、transformer 名称与计数 |
| `backup` | 给 .fmw 生成带时间戳的备份副本并回报 sha256 |

另有校准探针 `scripts/probe_api.py`：首次部署或 FME 版本变更时运行一次，
输出本机 fmeobjects 与 FMEWorkspaceRunner 的真实方法清单。操作手册见 `SKILL.md`。

### MCP Runner（live/）

纯标准库 stdio MCP 服务端，6 个工具，把执行收拢到唯一一条带闸路径上。
使用说明见 `live/RUNNER.md`，自检脚本 `live/selftest.py`。

| 工具 | 作用 | 风险 |
|---|---|---|
| fme_ping | runner 是否在线、fmeobjects 是否可用 | 只读 |
| fme_discover | 环境发现：导入尝试、安装候选、日志位置（校准用） | 只读 |
| fme_list_workspaces | 列目录下全部 .fmw | 只读 |
| fme_workspace_info | 解析 .fmw（文本尽力解析，可能不完整） | 只读 |
| fme_workspace_log_tail | 读最近运行日志尾部 | 只读 |
| fme_run_workspace | 无头运行一个 .fmw，参数以 JSON 传 published parameters（须 confirm=true） | **执行** |

## 架构

```
┌────────────────────────────────────────────────────────────────┐
│  你的 AI Agent / MCP 客户端（6 个 fme_* 工具）                   │
└──────────────────────────────┬─────────────────────────────────┘
                               │ MCP (stdio)
┌──────────────────────────────▼─────────────────────────────────┐
│  live/mcp_server.py（纯 Python 标准库）                          │
│  confirm 闸 → fmeobjects.FMEWorkspaceRunner → 运行 .fmw 文件    │
│  每次运行追加记录到 ~/.fme-agent-bridge/runs.jsonl              │
└────────────────────────────────────────────────────────────────┘

命令行：Agent → scripts/fme_bridge.py（preflight/scan/info/backup）→ JSON 回报
（命令行桥不执行 workspace，执行只走 MCP 的 run_workspace 一条路）
```

## 快速上手

1. 把整个目录放到装有 FME 的机器上，让你的 AI Agent 读 `SKILL.md` 并严格按它执行。
2. 先跑预检与盘点（结果式任务示例，路径按实际改）：

> 读 `<本目录>/SKILL.md` 并严格按它执行。目标结果：
> (1) 运行 preflight，回报 JSON 原文（fmeobjects 不可导入就停，不要 pip 装同名包）；
> (2) 运行 probe_api.py 并完整回传输出；
> (3) scan 我的 workspace 目录，再对其中一个 .fmw 跑 info，回报 JSON 原文，
> 并与我在 FME Workbench 里看到的 reader/writer/transformer 逐项核对。
> 本轮不运行任何 workspace。

3. 验收清单：
   - [ ] preflight 的 JSON 中 `fmeobjects_import` 为 ok
   - [ ] probe 输出包含 FMEWorkspaceRunner 的完整方法清单
   - [ ] info 的数据集与 transformer 计数与 Workbench 界面所见一致（不一致的如实记录）
   - [ ] backup 生成了带时间戳的副本且 sha256 非空
4. 要真正运行某个 workspace 时，再按 `live/RUNNER.md` 注册 MCP 服务端，
   并按 `docs/CALIBRATION.md` 先用无副作用的示例 workspace 试跑校准。

## 安全模型

- **唯一执行路径 + confirm 闸**：执行只经 `fme_run_workspace`，缺
  `confirm=true` 一律拒绝；confirm 只能在用户明确同意后填入。
- **绝不假装成功**：无 fmeobjects 时返回 `FME_NOT_AVAILABLE` 且 `ran=false`；
  runner 报错返回 `FME_RUN_FAILED` 并留原始报错。
- **运行日志留档**：每次运行尝试（成功/失败/不可用）都追加进
  `~/.fme-agent-bridge/runs.jsonl`，`fme_workspace_log_tail` 可回读。
- **先备份后运行**：SKILL.md 规定对要运行的 .fmw 先 backup；参数以 JSON
  对象显式传 published parameters，不许靠猜参数名。
- **可选 token 守卫**：设置 `FME_BRIDGE_TOKEN` 环境变量或
  `~/.fme-agent-bridge.token` 后，tools/call 须带一致的 `_token`，
  否则 BAD_TOKEN 拒绝。默认 stdio 本地信任，不要把服务端暴露到网络。

## 状态声明

- 已在无 FME 的环境验证：全部脚本语法（py_compile）、MCP 协议自检
  （`live/selftest.py`：initialize / 6 工具清单 / ping / discover /
  run 闸门 / bad-token / run 诚实性，全 PASS）、info 对自造 .fmw 样本的
  解析计数、backup 真实复制 + sha256、preflight 在无 FME 时的结构化报错。
- **fmeobjects 实机路径未验证**：FMEWorkspaceRunner 在真实 FME 安装上的
  导入位置、run/runWithParameters 的签名与返回语义、日志文件真实落盘
  位置、许可检出行为，都待使用者按 `docs/CALIBRATION.md` 在实机校准。
- 本包在 gis-agent-bridges 合集中的定位是"能做的都做"里最克制的一个：
  官方已有服务器侧 MCP，桌面端又无会话接口，只做诚实的无头窄缝。

## 环境要求

- 一份你自己合法持有的 FME 桌面授权（Form/Workbench 同版本即可；
  本项目不提供、不绕过任何许可机制）。
- 能 import 到 fmeobjects 的 Python 3（FME 自带 Python，或已把 FME
  安装目录配进环境的解释器）；MCP 服务端须以该解释器启动。
- 任一支持 stdio 的 MCP 客户端 / AI Agent。

## 目录结构

```
fme/
├── README.md            本文件
├── SKILL.md             操作手册（环境发现、命令、安全纪律、报错对照、回报格式）
├── ROADMAP.md           版本演进、待实机校准清单、后续候选
├── docs/
│   └── CALIBRATION.md   实机校准指南（顺序、验收标准、红线）
├── scripts/
│   ├── fme_bridge.py    命令行桥（preflight / scan / info / backup，单行 JSON 输出）
│   └── probe_api.py     校准探针，输出本机 fmeobjects 的真实方法清单
└── live/
    ├── mcp_server.py    MCP runner 服务端（stdio，纯标准库，6 个工具）
    ├── selftest.py      一键自检（无 FME 环境可跑协议层与诚实性）
    └── RUNNER.md        Runner 使用说明（定位、与官方 Flow MCP 的分工、纪律）
```

## 免责声明

本项目是独立的第三方开源工具，与 Safe Software Inc. 没有任何隶属、授权或
合作关系；FME、FME Flow、FME Form 等名称与商标归 Safe Software Inc. 所有，
本项目仅为互操作目的提及。使用本工具运行 FME workspace，需要你自备正版
FME 软件与授权，并自行对运行结果负责。本工具按现状提供，不附带任何明示
或默示担保（详见 LICENSE）。

## License

MIT，见 [LICENSE](LICENSE)。
