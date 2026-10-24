# Skill: globalmapper-bridge（Global Mapper 工程文件桥接）

让 AI Agent 通过 Global Mapper 官方 Python 模块 **globalmapper**（仅随
Global Mapper **Pro** 版提供）操作 Global Mapper 工程文件（工作区 *.gmw），
而不是直接读写工作区文件。本 Skill 只提供有限、受控的动作；动作之外的
一切操作（改数据、改符号、删图层）一律禁止自行发挥。

## 版本基线（开发基线）

- Global Mapper Pro（模块路线的前提；标准版只有 .gms 脚本语言，无 Python 模块）。
- Python 3.x，且该解释器能 import 到 globalmapper 模块。
- 若本机实际版本与上述不符，先停下回报版本差异，不要硬跑。
- 本桥定位无头为主；桌面 Script Editor 的“主视图上下文”只是半个会话接口，
  **不许向用户宣称本工具具备完整实时接入能力**。

## 运行前：环境发现（每个新会话先做一次）

1. 确认本机装的是 Global Mapper **Pro**，并定位能 import globalmapper 的
   Python 解释器（GM 配套 Python 环境，或按官方示例配置好模块路径的解释器；
   **不要使用或修改与本任务无关的既有项目环境**）。
2. 运行预检（见下），预检不过不许进入任何业务动作。
3. 首次部署或版本变更时，先运行一次校准探针 probe_api.py（见下），
   把候选函数命中清单完整回传。

## 动作清单（v0.1，仅此三项 + 探针）

所有动作通过桥接脚本执行，脚本输出单行 JSON，必须原样附在回报里。

### 1) preflight —— 环境预检（只读，无副作用）
```
<python> scripts/gm_bridge.py preflight
```
检查：Python 版本、globalmapper 模块可导入、模块版本（多策略）、
各功能组候选函数命中情况、安装线索（环境变量/常见安装目录）。

### 2) backup —— 备份工作区文件（只读原件）
```
<python> scripts/gm_bridge.py backup <工作区文件路径>
```
在同目录生成 `<原名>.bak-<yyyymmdd-HHMMSS><扩展名>` 副本并回报 sha256；
同时回报同名数据文件清单与工作区引用的外部文件存在性。
**注意：.gmw 只保存引用关系，只复制 .gmw 不等于备份了数据**；
任何写操作之前必须先 backup，且写操作只许作用于副本（见安全纪律）。
本 Skill 本身没有写动作。

### 3) inspect —— 工程盘点（只读）
```
<python> scripts/gm_bridge.py inspect <工作区文件路径>
```
两种模式，输出里以 `mode` 与 `complete` 如实标注：
- `headless-module`：用 globalmapper 模块打开临时副本（原件零接触），
  枚举图层（名称、命中策略 via），complete=true；
- `headless-partial-parse`：模块不可用或枚举为空时退化为只读解析 .gmw
  文本片段，只提取写明的数据文件名并以文件名为图层名推测，
  complete=false，**结果可能不完整、图层名可能与界面显示不一致**，
  回报时必须把这个限定说清，不许当成完整盘点。

### 校准探针 probe_api.py（仅首次部署或版本变更时运行一次）
```
<python> scripts/probe_api.py
```
输出本机 globalmapper 模块的版本候选、各功能组（load / layer_list /
layer_info / visible / zoom / export / close 等）候选函数命中清单与公开
名称全表，供维护者据此收紧桥接脚本。探针结果必须完整回传给用户/维护者，
不得据此自行扩展动作。

### MCP 服务端工具（live/mcp_server.py，共 7 个）

只读：ping / discover / workspace_info / list_layers /
export_workspace_image（只读出文件）；视图级：set_layer_visible /
zoom_to_layer。视图级工具带**上下文闸**：无头上下文下结构化返回
`NOT_IN_MAIN_VIEW_CONTEXT`，这是预期行为，不是故障；不许用伪造环境变量
等方式绕过闸门。详见 `live/LIVE.md`，实机校准按 `docs/CALIBRATION.md`。
v0.2 新增只读盘点 `scripts/verify_project.py --workspace <工程.gmw>`（可加 `--copy-to <新目录>` 做迁移验收；模块缺失时结构化报错）与工程手册 `ENGINEERING-PLAYBOOK.md`，做迁移/交付验收时按手册清单执行。

## 安全纪律（硬规则，违反即停）

1. **原件只读**：禁止对用户指定的原始工作区执行任何 save / 写入 / 删除动作。
   需要修改时，先 backup，再复制出一份工作副本，只改副本，并在回报中写明副本路径。
2. **禁止删除**任何图层、数据文件；禁止批量改属性数据。v0.1 无头桥没有写动作，
   遇到需要写的需求，停下回报，不要临时写脚本凑。
3. **GUI 占用**：若工作区正在 Global Mapper 中打开，无头 inspect 用的是临时
   副本、文本解析是只读字节，两者都不与 GUI 抢文件；但回报中要说明盘点的是
   磁盘上的已保存状态，可能不含 GUI 里未保存的改动。
4. **模块/版本错误即停**：模块不可用、候选函数全灭时，停下回报原始报错全文，
   不许换版本、换环境反复试（最多按报错表处置一次）。
5. **不许伪造上下文**：`GM_BRIDGE_CONTEXT=main-view` 只能在确实从 Script
   Editor 主视图上下文启动服务端时设置；为绕过上下文闸而设置属于造假，禁止。
6. **路径含中文/空格**一律用引号包裹并按原始字符串传参；JSON 输出保持 UTF-8 不转义。
7. 每一步的脚本原始输出（JSON）都要留档回传；失败也要回传，不许只报结论。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `GM_MODULE_NOT_AVAILABLE` | 当前解释器 import 不到 globalmapper 模块（标准版无此模块，或模块路径未配置） | 停。确认是 Pro 版并按官方示例配置模块路径后重跑 preflight；不要 pip 乱装同名包 |
| `FILE_NOT_FOUND` | 工作区路径不存在 | 核对路径原文后重试一次，仍失败则停 |
| `BACKUP_EXISTS` | 同一秒的目标备份已存在 | 等一秒后重试，或先确认已有备份可用 |
| `OPEN_WORKSPACE_FAILED` | 模块在位但全部加载候选失败 | 回报 attempts 原文；检查工作区版本是否高于模块版本，停下回报 |
| inspect 输出 mode=headless-partial-parse | 模块不可用/枚举为空，已退化为文本部分解析 | 如实使用：只作文件名级参考；需要完整盘点先解决模块问题 |
| `NOT_IN_MAIN_VIEW_CONTEXT` | 视图工具在无头上下文被闸住 | 预期行为；按 live/LIVE.md 的脚本上下文或文件投递方式处理，不要绕闸 |
| `NOT_SUPPORTED`（zoom/visible） | 本机版本公开 API 无对应入口或签名不合 | 回报 attempts；按 docs/CALIBRATION.md 记录为该版本的结构化结论 |
| `BAD_TOKEN` | 设置了 GM_BRIDGE_TOKEN 但调用未带匹配的 _token | 按服务端配置补 token，不要关闸 |

## 回报格式

每次动作后回报：①一句话结论；②脚本 JSON 原文；③若动过文件，列出新建文件路径清单。
没有 JSON 的回报视为未执行。inspect 为 partial-parse 时，结论句必须带“部分解析、可能不完整”。
