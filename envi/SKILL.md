# Skill: envi-bridge（ENVI 栅格无头桥）

让 AI Agent 通过 ENVI 栅格的 `.hdr` 头文件解析（纯 Python）与 IDL–Python
桥 **idlpy** 的无头 ENVITask 会话使用 ENVI 数据与算法，而不是附着 ENVI GUI。
**本包只有无头模式**：ENVI 没有官方支持的 GUI 会话附着通道（见 live/HEADLESS.md）。
本 Skill 只提供有限、受控的动作；动作之外一律禁止自行发挥。

## 版本基线（开发基线）

- 盘点层：Python 3.x，零依赖，与 ENVI 版本无关。
- 任务层：ENVI 5.x + IDL 8.x 的 idlpy 桥（以实机 probe 结果为准）；
  若本机实际版本与此差异明显，先停下回报，不要硬跑。

## 运行前：环境发现（每个新会话先做一次）

1. 定位装有 idlpy 的 Python 解释器（ENVI/IDL 自带环境或用户指定环境；
   **不要使用或修改与本任务无关的既有项目环境**）。
2. 运行 `scripts/probe_api.py` 回报 idlpy 可用性、ENVI 版本与 ENVITask 抽样；
   探针显示 ENVI 会话不可用时，只许使用盘点层动作（inventory / raster_info）。
3. 运行 preflight（见下），确认 idlpy 状态后再考虑任何任务层动作。

## 动作清单（v0.1，仅此这些）

### 无头脚本（输出单行 JSON，必须原样附在回报里）

```
<python> scripts/envi_bridge.py preflight
<python> scripts/envi_bridge.py inventory <目录 | .hdr | 栅格数据文件>
<python> scripts/envi_bridge.py backup <栅格数据文件 | .hdr>
```

- preflight：检查 .hdr 解析能力、idlpy 可导入性、安装线索；idlpy 不可用时
  返回 `IDLPY_NOT_AVAILABLE`（退出码 1），盘点层不受影响。
- inventory：纯 Python 解析 .hdr，回报 samples/lines/bands、data type、
  interleave、map info、band names、wavelength，以及期望字节数与实际
  文件大小的核对结果（`size_matches`）。拿不到的字段为 null，不许猜。
- backup：把数据文件 + .hdr 成对复制为 `<原名>.bak-<yyyymmdd-HHMMSS><扩展名>`，
  回报各自 sha256；缺一半（无 .hdr 或无数据文件）直接报错，拒绝备份残缺对。

### MCP 工具（live/mcp_server.py）

- 只读：envi_ping、envi_discover、envi_raster_info、envi_list_tasks、envi_describe_task。
- 写类：envi_run_task、envi_export_raster_subset，**必须带 confirm=true**，
  且 confirm 只能在用户明确同意后填入。
- 无 ENVI 时 list/describe/run/export 返回结构化 `ENVI_NOT_AVAILABLE`
  （export 返回 `NOT_SUPPORTED_IN_HDR_MODE`），这就是最终结果，不许换说法重试。

### 校准探针 probe_api.py（仅首次部署或版本变更时运行一次）

```
<python> scripts/probe_api.py
```
输出 .hdr 解析自检、idlpy 可用性、ENVI/IDL 版本与 ENVITask 名单抽样。
探针结果必须完整回传，不得据此自行扩展动作。

## 安全纪律（硬规则，违反即停）

1. **原件只读**：禁止对用户指定的原始栅格执行就地改写。run_task 前先 backup，
   任务的输出路径必须指向工作副本目录，并在回报中写明。
2. **禁止删除**任何栅格或头文件；禁止批量覆盖既有结果文件。
3. **不许冒充实时**：不得向用户声称 Agent 正在操作他打开的 ENVI 窗口；
   本包一切执行都发生在无头会话里，回报时必须说清。
4. **许可/版本错误即停**：ENVI 会话启动失败、许可报错，停下回报原始报错全文，
   不许换环境反复试（最多按报错表处置一次）。
5. **不许伪造执行**：没有 ENVI 时，绝不许拿 .hdr 盘点结果或本地 numpy 式
   计算冒充 ENVITask 执行结果。
6. **路径含中文/空格**一律用引号包裹并按原始字符串传参；JSON 输出保持 UTF-8 不转义。
7. 每一步的原始输出（JSON）都要留档回传；失败也要回传，不许只报结论。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `IDLPY_NOT_AVAILABLE` | 当前解释器没装 idlpy，或 IDL 桥不可用 | 只用盘点层；要跑任务先按"环境发现"换到 ENVI 自带解释器，不要 pip 装进无关环境 |
| `ENVI_NOT_AVAILABLE` | idlpy 可导入但 ENVI 会话启动失败（多半许可） | 停。回报原始报错，请用户检查 ENVI/IDL 许可后重跑 probe |
| `HDR_NOT_FOUND` / `NO_HDR_FOUND` | 目标旁没有同名 .hdr | 如实回报；可能是非 ENVI 格式栅格，不要自行编造头信息 |
| `size_matches=false` | 数据文件字节数与 .hdr 描述不符 | 这是盘点要发现的问题：可能截断、头被改过或 interleave 不符；如实写入回报，不要自动修复 |
| `TASK_NOT_FOUND` | ENVITask 名不存在或构造失败 | 先用 envi_list_tasks / probe 的抽样名单核对真实任务名，不要猜名重试 |
| `CONFIRM_REQUIRED` | 写类工具没带 confirm | 停下向用户确认，拿到明确同意后由用户侧填入 confirm=true 再执行 |

## 回报格式

每次动作后回报：①一句话结论（并注明是盘点层还是任务层结果）；
②脚本/工具 JSON 原文；③若动过文件，列出新建文件路径清单。
没有 JSON 的回报视为未执行；无头会话里跑过的任务，回报必须包含
`executed: true` 与 via 字段，缺一律视为未执行。

v0.2（2026-10-24）：selftest 改后台线程+队列读行（弃 select，修 Windows 管道问题）；新增 scripts/verify_project.py（.hdr 文件对盘点 + 伴生文件完整性 + --copy-to 副本重盘）与 ENGINEERING-PLAYBOOK.md；token 仍只用环境变量 ENVI_BRIDGE_TOKEN（无 token 文件）；工具清单（7 个）、confirm 闸与 BAD_TOKEN 语义不变，仍仅无头，idlpy 任务层未做实机校准。
