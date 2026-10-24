# 工程文件生产手册（FME / .fmw 适配版，未实机验证）

本手册把 SuperMap 包 2026-10-24 实机校准沉淀的通用工程纪律，按 FME 的形态
（仅无头 runner、无当前会话接口）改写。**本包尚未在真实 FME 上校准**：
手册里涉及 `fmeobjects` / `FMEWorkspaceRunner` 签名与行为的说法都是待实机
验证的假设，纪律部分（先备份、写后核查落盘等）是通用要求、立即生效。

与官方的关系先说清：服务器场景（发布、调度、权限治理）用 Safe Software
官方的 **FME Flow MCP Server**；本包只补本地桌面授权下直接跑 .fmw 的窄缝，
两者互补。本手册只约束本包的本地无头路线。

## 1. 原件只读：先备份、运行只此一条路

- 运行任何 .fmw 之前，先用 `scripts/fme_bridge.py backup` 生成带时间戳的
  备份副本（回报含 sha256）。本包不提供修改 .fmw 定义的动作；要改行为
  只能经 run_workspace 的 parameters 传已发布的 published parameters。
- 盘点类动作（scan / info / verify_project.py）全部只读：info 是对 .fmw
  文本的只读解析，不打开 FME、不写任何文件。
- 执行只有一条路：`live/mcp_server.py` 的 `fme_run_workspace`（confirm 闸
  + 运行日志）。不许用命令行、Tcl 或临时脚本绕开 runner 私自运行。

## 2. 伴生文件完整性（.fmw 引用的数据要成套）

- .fmw 定义的是读写流程，真实数据在它引用的源/目标路径上。迁移一个
  workspace 不只是搬 .fmw，还要盘清它引用的数据集是否成套、是否跟得走。
- Shapefile 数据集是成套文件：`.shp/.shx/.dbf` 缺一不可，`.prj/.cpg`
  缺失分别丢坐标系与编码信息。`verify_project.py` 会逐个数据集核对
  伴生集，缺必需件记为 issue。
- 栅格等其他格式同理：`.hdr` 等同主名成组文件按伴生集整体看待。
- 数据集路径里含宏 `$(...)` 的，静态盘点定不了存在性（verify 输出
  exists=null 并记 issue）——要在 Workbench 里展开核对，不要猜。

## 3. 相对路径风险

- .fmw 里的数据集路径常是相对路径或宏路径：workspace 换目录、换机器后，
  相对路径按新位置重新解释，源数据“找不到”、目标写到意料之外的目录，
  都是这类断链的典型症状，先怀疑路径，不要先怀疑数据。
- 迁移验收必须走 `verify_project.py --copy-to`：复制 .fmw + 同主名伴生
  + 同目录被引用 .shp 的伴生集后，对副本重新盘点，而不是只看复制成功。
- 绝对路径（含盘符）的引用换机器必然断链，盘点回报里要单独点名；
  运行前先向用户确认目标路径可被写，别让一次校准运行改写真实业务数据。

## 4. 运行后核查落盘（不信 runner 返回，警惕假成功）

- `ran=true` 只表示 runner 调用无异常返回。运行之后必须核查**输出文件
  真实落盘**（目标路径、字节数、修改时间），并用 `fme_workspace_log_tail`
  回读日志尾部核对读写要素计数与警告行，三者对上才许报“运行成功”。
- SuperMap 校准实测过“假成功”（调用不报错但效果不落盘）；FME 侧同理：
  参数键名传错、目标路径不可写等情况，要以日志原文与落盘证据定论，
  不许只凭返回码粉饰。
- 每次运行尝试（成功 / 失败 / FME 不可用）都会追加进本桥运行日志
  `~/.fme-agent-bridge/runs.jsonl`；回报时附对应条目，没有条目视为未执行。

## 5. GUI / 无头边界（如实写）

- FME 没有“当前会话”接口：本包拿不到 Workbench 里正打开的 workspace
  的未保存状态，运行的永远是磁盘上的 .fmw 文件本身。不要向用户宣称
  本包能操作“当前打开的工程”。
- 无头 runner 不弹窗、不刷新任何界面；Workbench 里改了 workspace 没保存，
  本桥盘点与运行看到的都还是旧版本——回报时注明盘的是磁盘版本。
- 服务器侧的发布与调度不在本包范围：需要时按官方 Flow MCP 的流程走，
  本包的盘点结果（verify_project.py 输出）可作为交接清单的输入。

## 6. 导出 / 输出注意

- workspace 的输出即其 writer 定义的目标：运行前先用 info / verify 输出
  核对目标数据集清单与路径，确认写入位置无害（临时目录或用户指定处）。
- published parameters 只传 Workbench 里核对过的键名；传错键名得到的
  `FME_RUN_FAILED` 要带原始报错如实回传，不许连环改名重试碰运气。
- 输出数据成套性同第 2 节：运行后核查目标 .shp 等数据集的伴生集齐全，
  缺件时说明是 writer 配置问题还是中途失败，不许只报主文件存在。

## 7. 迁移验收（用 verify_project.py）

```
<python> scripts/verify_project.py --workspace <job.fmw>
<python> scripts/verify_project.py --workspace <job.fmw> --copy-to <新目录>
```

交付/迁移前清单：

1. .fmw + 同主名伴生 + 被引用数据整组复制到新路径，对副本重跑盘点。
2. 源/目标数据集逐项核对：存在性、.shp 伴生集、宏路径在 Workbench
   里展开后是否仍指得通。
3. transformer 计数与 Workbench 界面一致，或差异逐条有书面解释
   （宏 / INCLUDE / 注释误计）。
4. `issues` 列表逐条有处置或书面说明。
5. 试跑（经用户确认）后：输出文件真实落盘、日志尾部可回读、
   runs.jsonl 有对应条目。
6. 原 .fmw 的 backup 副本在位且 sha256 非空。

## 8. 失败如实回报

- `FME_NOT_AVAILABLE` / `FME_RUN_FAILED` / `FMEOBJECTS_INCOMPLETE` 都是
  结构化结论：带原始信息回报，`ran=false` 就是没有运行，不许换说法。
- 许可/版本报错即停，回报原文，不许换环境反复试探，更不许 pip 安装
  来历不明的同名 fmeobjects 包凑数。
- info 的文本解析偏差如实记录并以 Workbench 界面为准，不许改解析
  结果凑数。
