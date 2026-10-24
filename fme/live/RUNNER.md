# Runner 使用说明（FME 无头 Runner + MCP 接入，v0.1）

## 定位：与官方 FME Flow MCP 的分工

Safe Software 官方已推出 **FME Flow 的 MCP Server**：把发布到 Flow 的
workspace 注册为 MCP 工具，带 OAuth 与官方权限治理。**服务器场景
（发布、调度、多人使用、权限审计）请直接用官方 Flow MCP。**

本包的 runner 只补一条官方没覆盖的窄缝：**在本机桌面版 FME 授权下，
直接以无头方式运行一个 .fmw 文件**——不开 Workbench 界面、不先发布到
Flow，适合本地盘点后立刻试跑、校准、批处理前验证。两者互补，不竞争。

另注意：FME 没有"当前会话"接口，本 runner 拿不到 Workbench 里正打开的
workspace 的未保存状态，它运行的永远是磁盘上的 .fmw 文件本身。

## 启动两步

1. 确认运行环境：先按 SKILL.md 跑一遍 `scripts/fme_bridge.py preflight`，
   查清哪个解释器能 import fmeobjects。MCP 服务端必须用**那个**解释器
   启动，否则 run_workspace 只会返回 FME_NOT_AVAILABLE。
2. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端：
   - command：能 import fmeobjects 的 Python 3 解释器
   - args：`<本目录>/live/mcp_server.py`
   注册后客户端应能列出 6 个 fme_* 工具。

接入前可先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / 工具清单 / ping / discover / run 闸门 / bad-token /
run 诚实性，全 PASS 才说明包本身没坏；它不验证与真实 FME 的对接）。

可选 token 守卫：设置环境变量 `FME_BRIDGE_TOKEN`，或把 token 写进
`~/.fme-agent-bridge.token`，之后每次 tools/call 须在参数里带一致的
`_token`，否则被 BAD_TOKEN 拒绝。不要把 token 发给任何人；不要把本
服务端暴露到网络（stdio 本地使用）。

## 工具清单（v0.1，共 6 个）

风险等级：只读＝无副作用；执行＝真实运行 workspace、按其定义读写数据，
带 confirm=true 闸（confirm 只能在用户明确同意后填）。

| 工具 | 作用 | 风险 |
|---|---|---|
| fme_ping | runner 是否在线、fmeobjects 是否可用 | 只读 |
| fme_discover | 环境发现：导入尝试、安装候选、日志位置（校准用） | 只读 |
| fme_list_workspaces | 列目录下全部 .fmw（名称/路径/大小/修改时间） | 只读 |
| fme_workspace_info | 解析 .fmw：源/目标数据集与 transformer 计数（文本尽力解析，可能不完整） | 只读 |
| fme_workspace_log_tail | 读某 workspace 最近运行日志尾部 | 只读 |
| fme_run_workspace | 无头运行一个 .fmw；parameters 以 JSON 对象传 published parameters（须 confirm=true） | **执行** |

## 运行与日志

- 每次 run_workspace 尝试（成功、失败、fmeobjects 不可用）都会追加一条
  记录到 `~/.fme-agent-bridge/runs.jsonl`：时间、workspace、参数、状态、
  耗时。这是本桥自己的运行日志，与 FME 自身的 .log 并存。
- fme_workspace_log_tail 的查找顺序：显式 log_path → workspace 同目录
  的 `<名>.log` / `<名>_log.txt` / `<名>.fmw.log` → 本桥 runs.jsonl 中
  该 workspace 的记录。都找不到返回 NO_LOG_FOUND，不许编造日志内容。
- run_workspace 的诚实语义：`ran=true` 只在 runner 调用无异常返回时出现；
  无 fmeobjects 返回 FME_NOT_AVAILABLE、runner 报错返回 FME_RUN_FAILED，
  两者都带 `ran=false`。见到 ran=false 就如实回报，不许换说法。

## 纪律

- 运行前先用命令行桥 backup 该 .fmw，并向用户确认 workspace 的写入
  目标路径可被写；不要对清单外的 workspace 擅自运行。
- parameters 只传已发布的 published parameters，键名以 Workbench 里
  核对过的为准；传错键名得到的 FME_RUN_FAILED 要如实回传，不要连环改名重试。
- 许可报错即停，回报原始报错全文（对照 SKILL.md 报错表处置）。
- 首次实机使用按 `docs/CALIBRATION.md` 的顺序校准（先 preflight 钉死
  导入策略，再用无副作用示例 workspace 试跑）。
