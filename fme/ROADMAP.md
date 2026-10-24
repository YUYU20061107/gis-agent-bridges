# ROADMAP —— FME 无头 Runner 演进与待校准清单

## 定位前提

FME 没有"当前会话"接口，官方又有 FME Flow MCP Server 覆盖服务器场景，
所以本包没有、也不会有"实时桥"。演进方向只有一个：在本地无头这一条窄缝里
把盘点、解析、受控运行做扎实。

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | 命令行桥四动作：preflight（多策略探测 FME/fmeobjects）、scan（.fmw 清单）、info（.fmw 文本尽力解析：数据集＋transformer 计数）、backup（时间戳备份+sha256）；探针 probe_api.py；MCP runner 6 工具（只读 5 个＋带 confirm 闸的 run_workspace），运行日志 runs.jsonl 留档，可选 token 守卫 | VM 侧已验证：py_compile、selftest 全 PASS、info 对自造样本解析计数、backup 真复制、无 FME 时结构化报错；**fmeobjects 实机路径未验证** |

## 待实机校准清单（按依赖顺序）

1. **fmeobjects 导入位置**：目标 FME 版本下，哪个解释器能直接 import
   fmeobjects（FME 自带 Python 的确切路径与版本），还是需要把安装目录
   加入 sys.path；discover 的多策略顺序按实机结果收紧。
2. **FMEWorkspaceRunner 真实签名**：run / runWithParameters 的参数与返回
   语义（返回 None 靠异常报错，还是有状态可读）；published parameters
   字典的键名与取值类型（字符串化要求）。
3. **许可检出行为**：无许可/许可被 GUI 占用时 runner 的报错原文，
   补进 SKILL.md 报错对照表。
4. **日志真实落盘位置**：实机运行后 .log 到底落在哪（workspace 同目录的
   哪个命名），据实修正 workspace_log_tail 的候选顺序。
5. **info 解析对账**：拿 2–3 个真实 .fmw 与 Workbench 界面逐项对
   （reader/writer 关键词、数据集指令、FACTORY_DEF 计数），记录解析
   偏差的类型（宏、INCLUDE、注释误计），必要时收紧正则。

## 后续候选（均未立项，先实机校准再说）

- **published parameters 清单提取**：从 .fmw 文本解析已发布参数的定义
  （名字/默认值/提示），让 run 前能对参数表，不必靠猜。
- **批量运行队列**：对 scan 清单里的多个 workspace 逐个 confirm 后顺序
  运行，逐个留日志；仍逐个过闸，不做"一键全跑"。
- **日志结构化摘要**：从 FME 日志里提取读写要素计数、警告与报错行，
  给 log_tail 加摘要模式。
- **与官方 Flow MCP 的衔接说明**：当本地 workspace 需要发布到 Flow 时，
  给出从本包盘点结果到官方流程的交接清单（只做文档，不做发布动作）。
