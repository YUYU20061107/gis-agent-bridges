# 实机校准指南 —— FME 无头 Runner v0.1 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述要达成的
结果、验收标准与红线，具体做法由执行者决定；但每一步的原始输出必须留档
回传，没有 JSON 原文的回报视为未执行。

## 目标结果（全部达成才算完成）

1. preflight 在目标机器上通过：fmeobjects 可导入、FMEWorkspaceRunner
   存在，并查清命中的导入策略（哪个解释器 / 是否需要安装目录入 sys.path）。
2. scan / info 的结果与 FME Workbench 界面逐项对得上（允许 info 有已知
   解析偏差，但偏差必须被记录，而不是被掩盖）。
3. 一个无副作用的示例 workspace 经 run_workspace 试跑成功：ran=true、
   运行日志有对应条目、log_tail 能回读到日志、输出文件真实落盘。
4. 校准结论回写进代码与文档：导入策略顺序、日志候选顺序按实机收紧，
   报错对照表补上实机许可报错原文，并跑一遍 live/selftest.py 保持全 PASS。

## 校准顺序（不要跳步）

1. **先 preflight + probe**：完整回传 preflight JSON 与 probe_api.py 输出
   （fmeobjects 来源路径、版本线索、FMEWorkspaceRunner 方法清单）。
   preflight 不过就停在这里，先解决导入/许可，不许往下走。
2. **scan / info 对账**：对一个已知内容的真实 workspace 目录跑 scan，
   对其中 1 个 .fmw 跑 info，逐项与 Workbench 界面核对：reader/writer
   关键词、源/目标数据集、transformer 计数。差异逐条记录（注明是宏、
   INCLUDE 还是注释误计），以界面为准。
3. **无副作用示例试跑**：准备一个只读输入、只写到临时目录的示例
   workspace（或用户指定的无害 workspace）；先 backup，再经用户当场
   确认后用 run_workspace 运行（parameters 只传已核对的 published
   parameters）。核对：ran=true、runs.jsonl 有条目、输出文件落盘、
   log_tail 读到日志尾部。
4. **负例验证**：对同一示例改传一个错误的参数键名运行一次，确认返回
   FME_RUN_FAILED 且原始报错被如实回传（验证"绝不假装成功"在实机成立）。
5. **收紧与回归**：按实机结果改导入策略与日志候选顺序、补报错表；
   跑 selftest；把改动点逐条列清回传。

## 每项验收标准

- preflight：JSON 中 `fmeobjects_import` 为 ok，`fmeobjects_file` 指向
  真实 FME 安装来源（不是来历不明的同名包）。
- probe：FMEWorkspaceRunner 方法清单完整回传，run/runWithParameters 在列。
- scan：.fmw 清单与目录实际文件一致（数量、大小）。
- info：数据集与 transformer 计数与界面一致，或差异有逐条书面解释。
- run_workspace：示例 workspace ran=true；输出文件真实存在；
  runs.jsonl 条目含 workspace、参数、耗时；log_tail 返回真实日志尾部。
- 负例：错误参数键名得到 FME_RUN_FAILED，回报含原始报错。

## 回报格式

每个动作一条：①一句话结论；②JSON 原文；③界面证据（截图或具体文字）；
④差异/报错原文。最后附：改动文件清单 + selftest 输出原文 + 仍未解决项清单。

## 红线（违反任意一条立即停下回报）

- **不碰无关环境**：不要使用、安装或修改与本任务无关的既有项目环境；
  尤其不要 pip 安装同名 fmeobjects 包。
- **先备份后运行**：任何 workspace 运行前先 backup；只许运行校准清单里
  点名的 workspace，不许顺手跑目录里其他文件。
- **confirm 只能由用户给**：run_workspace 的 confirm=true 必须经用户
  当场明确同意后才许填入，不许自作主张绕过闸口。
- **输出路径先确认**：试跑前先确认示例 workspace 的写入目标是临时目录
  或用户指定的无害位置，不许让校准运行改写真实业务数据。
- 许可/版本报错即停，回报原始报错全文，不许换版本、换环境反复试探。
- 不许自行扩展工具集或动作范围；发现 API 与脚本假设不符，回报现场
  方法清单，等维护者据实收紧。

## 从 SuperMap 实机校准迁移的通用教训（2026-10-24）

SuperMap 包已在 iDesktop 10i 上完成一轮实机校准（结论见 SuperMap 包的
`docs/CALIBRATION-RESULTS-20261024.md`）。其中与软件无关的通用教训已迁移
到本包；**本包自身仍未在真实 FME 上校准**，下表如实区分“已落到代码/文档”
与“仍是待本软件实机验证的假设”。

### 已落到本包代码 / 文档

| 教训（SuperMap 实测） | 本包落地形态 |
|---|---|
| Windows 下 `select()` 不能等子进程管道句柄（WinError 10038），须改后台线程 + 队列逐行读取 | `live/selftest.py` 已改用与 SuperMap 同款的 `_LineReader`（线程 + queue），删 `import select` |
| 只读盘点 + 结构化报错 + issues 列表，是迁移验收的可靠形态；异常不许裸 traceback；相对路径引用须连带盘点 | 新增 `scripts/verify_project.py`：纯 Python 解析 .fmw 提取源/目标数据集并校验存在性与 .shp 伴生完整性，`--copy-to` 复制后对副本重开盘点；fmeobjects 缺失时输出 `{"ok": false, "error": "FME_NOT_AVAILABLE", ...}` 并 exit 1 |
| “假成功”真实存在：调用不报错 ≠ 结果可用，须以落盘文件与日志为准 | 已写入 `ENGINEERING-PLAYBOOK.md` 第 4 节：运行后核查输出落盘 + log_tail 回读 + runs.jsonl 条目三者对上才许报成功 |
| 先备份后动工程、原件只读、相对路径风险、迁移验收清单等工程纪律与具体软件无关 | 已写入 `ENGINEERING-PLAYBOOK.md`（FME 适配版）第 1/2/3/7 节 |
| 服务器场景已有官方方案时，本包只补本地窄缝、不与官方竞争 | 手册与本指南继续明确与官方 FME Flow MCP 的互补分工（既有口径，未变） |

注：SuperMap 的 token 文件环境变量（`SM_BRIDGE_TOKEN_FILE`）与本包无关；
本包的 token 守卫仍是 `FME_BRIDGE_TOKEN` 环境变量或既有 token 文件
（`~/.fme-agent-bridge.token`，v0.1 既有设计），本次未改动其语义。

### 仍是待本软件实机验证的假设（不要当成结论）

- `fmeobjects` 在目标 FME 版本下的真实导入位置与解释器，仍靠
  `scripts/probe_api.py` 与 preflight 在实机钉死。
- `FMEWorkspaceRunner.run / runWithParameters` 的签名、返回语义与
  published parameters 的键名/取值类型，未有实机证据。
- 许可检出行为（无许可 / 被 Workbench 占用时的报错原文）未验证，
  待实机补进 SKILL.md 报错对照表。
- FME 运行日志的真实落盘位置与命名未验证，`workspace_log_tail` 的
  候选顺序仍是假设。
- info / verify 的文本解析与真实 .fmw 的对账偏差（宏 / INCLUDE / 注释
  误计）未在真实样本上测过；SuperMap 的软件专属 API 事实不类比套用。
