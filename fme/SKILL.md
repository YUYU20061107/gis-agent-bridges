# Skill: fme-headless-runner（FME 无头运行桥）

让 AI Agent 在本地无头运行 FME workspace 文件（*.fmw）：盘点、解析、备份，
并经唯一的 MCP runner 执行。FME 没有"当前会话"接口，本 Skill 不接入任何
FME 图形界面会话；服务器场景（发布/调度/治理）请用 Safe Software 官方的
FME Flow MCP Server，本包只补本地桌面授权下跑 .fmw 的窄缝。
本 Skill 只提供有限、受控的动作；动作之外不许自行发挥。

## 版本基线

- FME 桌面版（Form/Workbench）+ 其官方 Python API `fmeobjects`，Python 3.x。
- 若本机实际版本与桥接脚本假设不符，先停下回报差异，不要硬跑。

## 运行前：环境发现（每个新会话先做一次）

1. 运行预检（见下）；fmeobjects 导入不过，不许进入任何业务动作，
   更不许 pip 安装来历不明的同名包凑数。
2. 首次部署或 FME 版本变更时，运行一次校准探针 probe_api.py 并完整回传。
3. 明确本次要操作的 workspace 目录与文件清单，不许对清单外的 .fmw 擅自运行。

## 动作清单（v0.1，仅此这些）

### 命令行桥（全部只读或只读原件，输出单行 JSON，必须原样附在回报里）

```
<python> scripts/fme_bridge.py preflight
<python> scripts/fme_bridge.py scan <目录>
<python> scripts/fme_bridge.py info <某个 .fmw>
<python> scripts/fme_bridge.py backup <某个 .fmw>
```

- `preflight`：多策略探测 FME 安装与 fmeobjects 可导入性、FMEWorkspaceRunner 是否存在。
- `scan`：扫描目录列出 .fmw 清单（路径/大小/修改时间）。
- `info`：解析 .fmw 文本，提取源/目标数据集与 transformer 计数。
  结果标注 `mode=file-parse`、`complete=false`：这是尽力解析，可能不完整，
  引用时要带上这个口径，不许当成权威清单。
- `backup`：在同目录生成 `<原名>.bak-<yyyymmdd-HHMMSS>.fmw` 副本并回报 sha256。
  **任何运行之前必须先 backup 该 .fmw**。

### MCP Runner（执行只许走这一条路）

注册 `live/mcp_server.py`（启动解释器必须能 import fmeobjects）后可用 6 个工具：
fme_ping / fme_discover / fme_list_workspaces / fme_workspace_info /
fme_workspace_log_tail（只读），以及唯一的执行工具：

```
fme_run_workspace(path=<.fmw>, parameters={<published parameters 的 JSON 对象>}, confirm=true)
```

- parameters 只传 workspace 里已发布的 published parameters，键名以
  Workbench 里看到的为准，不许猜。
- confirm=true 只能在用户明确同意运行该 workspace 后填入。
- 运行后立即用 fme_workspace_log_tail 回读日志，并回报运行记录
  （`~/.fme-agent-bridge/runs.jsonl` 中对应条目）。

### 校准探针 probe_api.py（仅首次部署或版本变更时运行一次）

```
<python> scripts/probe_api.py
```
输出本机 fmeobjects 的模块位置、版本线索与 FMEWorkspaceRunner 方法清单，
必须完整回传给用户/维护者，不得据此自行扩展动作。

## 安全纪律（硬规则，违反即停）

1. **先备份后运行**：运行任何 .fmw 前先 backup；运行结果（输出数据）落在
   workspace 定义的目标路径上，运行前先向用户确认目标路径可被写。
2. **禁止改 workspace 定义**：v0.1 没有修改 .fmw 内容的动作；需要改参数
   只能经 run_workspace 的 parameters 传 published parameters，不许直接
   编辑 .fmw 文本凑结果。
3. **执行唯一路径**：不许绕开 MCP runner 用命令行、Tcl 或其他方式私自
   运行 workspace；命令行桥刻意不提供 run 动作。
4. **许可/版本错误即停**：fmeobjects 导入失败、许可检出报错、FME 版本与
   workspace 要求不符时，停下回报原始报错全文，不许换环境反复试探。
5. **如实回报**：`ran=false` 就是没有运行；FME_NOT_AVAILABLE /
   FME_RUN_FAILED 必须带原始信息回报，不许把失败粉饰成成功。
6. **路径含中文/空格**一律用引号包裹并按原始字符串传参；JSON 输出保持
   UTF-8 不转义。每一步的脚本原始输出（JSON）都要留档回传。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `FME_NOT_AVAILABLE` | 当前解释器 import 不到 fmeobjects | 换 FME 自带 Python 或按 discover 的安装候选配环境；不要 pip 装同名包 |
| `FMEOBJECTS_INCOMPLETE` | fmeobjects 缺 FMEWorkspaceRunner | 回报 fmeobjects 实际来源路径与版本线索，停 |
| `FME_RUN_FAILED` | runner 抛错（许可、参数名错误、数据路径不存在等） | 回报原始报错 + log_tail 结果；先核对 published parameters 键名与数据路径，不要连环重试 |
| `WORKSPACE_NOT_FOUND` / `FILE_NOT_FOUND` | .fmw 路径不对 | 核对路径原文后重试一次，仍失败则停 |
| `NO_LOG_FOUND` | 该 workspace 未经本桥运行过、且旁边无日志文件 | 如实回报；可先跑一次校准示例再看日志 |
| info 计数与界面不一致 | 文本解析的已知局限（宏/INCLUDE/注释） | 如实记录差异，以 Workbench 界面为准，不要改解析结果凑数 |

## 回报格式

每次动作后回报：①一句话结论；②脚本/工具 JSON 原文；③若动过文件，
列出新建文件路径清单；④涉及运行时，附运行日志条目与 log_tail 摘要。
没有 JSON 的回报视为未执行。
