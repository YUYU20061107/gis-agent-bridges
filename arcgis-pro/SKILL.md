# Skill: arcgis-pro-bridge（ArcGIS Pro 工程文件桥接）

让 AI Agent 通过 Esri 官方 Python 站点包 **arcpy** 操作 ArcGIS Pro 工程文件
（工程 *.aprx、文件地理数据库 *.gdb），而不是让 Agent 直接读写二进制文件。
本 Skill 只提供有限、受控的动作；动作之外的一切操作（改数据、改符号、删图层、
跑任意代码/任意 GP 工具）一律禁止自行发挥。**工具面收窄是有意的取舍**：
本桥不提供 execute_python 类任意代码执行工具，也不提供任意地理处理调用口，
Agent 能做的事被限定在可枚举、可审计的集合内。

## 版本基线（开发基线）

- ArcGIS Pro 3.x（Windows），自带 Python 环境 `arcgispro-py3`（Python 3.11 系），arcpy 随 Pro 安装。
- 若本机实际版本与上述不符，先停下回报版本差异，不要硬跑。

## 运行前：环境发现（每个新会话先做一次）

1. 定位 ArcGIS Pro 安装目录（注册表 `HKLM\SOFTWARE\ESRI\ArcGISPro` 的 InstallDir，
   或 `C:\Program Files\ArcGIS\Pro`）。
2. 定位带 arcpy 的解释器：优先 Pro 自带环境的
   `bin\Python\envs\arcgispro-py3\python.exe`，或官方启动器 `propy`
   （`bin\Python\Scripts\propy.bat`，用法：`propy 脚本.py 参数`）。
   **不要使用或修改与本任务无关的既有项目环境（包括其他 Conda 环境），
   也不要往 Pro 自带环境里 pip 安装任何东西。**
3. 运行预检（见下），预检不过不许进入任何业务动作。

## 动作清单（v0.1，仅此三项无头动作 + 实时桥工具）

> v0.2（2026-10-24）：selftest 改后台线程 + 队列读行；token 文件可用环境变量 `ARCGIS_PRO_BRIDGE_TOKEN_FILE` 指定；新增 `scripts/verify_project.py` 与 `ENGINEERING-PLAYBOOK.md`。工具清单、端口与 confirm 闸不变；仍未实机验证。

无头动作通过桥接脚本执行，脚本输出单行 JSON，必须原样附在回报里。

### 1) preflight —— 环境与许可预检（只读，无副作用）
```
<python> scripts/arcgis_bridge.py preflight
```
检查：Python 版本、arcpy 可导入、GetInstallInfo（版本/安装目录/许可级别）、
ProductInfo、arcpy.mp 可用性。当前解释器没有 arcpy 时返回结构化错误
`ARCPY_NOT_AVAILABLE`，并附多策略定位到的 Pro 自带 Python 候选路径——
按候选路径换解释器重跑，不要 pip 硬装 arcpy（arcpy 无法脱离 Pro 安装单独安装）。

### 2) backup —— 备份工程文件（只读原件）
```
<python> scripts/arcgis_bridge.py backup <工程文件 .aprx 路径>
```
在同目录生成 `<原名>.bak-<yyyymmdd-HHMMSS>.aprx` 副本并回报 sha256；
与 .aprx 同名的 .gdb 文件夹若存在，整体复制为 `<原名>.bak-<时间戳>.gdb`
并回报文件数与清单哈希。**任何写操作之前必须先 backup，且写操作只许作用于副本**。

### 3) inspect —— 工程盘点（只读，只看已保存状态）
```
<python> scripts/arcgis_bridge.py inspect <工程文件 .aprx 路径>
```
脚本会先把 .aprx（及同名 .gdb）复制到临时目录再打开（原件零接触），输出 JSON：
工程路径/默认地理数据库、每幅地图的名称与图层（名称、显隐、数据源、是否断裂、
标注开关）、独立表、布局（页面宽高、地图框数）。拿不到的字段为 null 并在
`notes` 里说明原因，不许猜。

**【必须向用户明示的口径】** inspect 是外部进程打开工程文件，
**只能看到上次保存到磁盘的状态，看不到 ArcGIS Pro 界面里的未保存修改**。
输出固定带 `mode: headless-saved-state`。向用户汇报盘点结果时必须带上这句限定，
不许把盘点结果说成界面实时状态。要看实时状态，走实时桥（live/）。

### 校准探针 probe_api.py（仅首次部署或版本变更时运行一次）
```
<python> scripts/probe_api.py [.aprx 路径]
```
输出本机 arcpy 版本/许可、arcpy.mp 关键类（ArcGISProject / Map / Layer / Table /
Layout / MapFrame）的真实方法清单，并实测 `ArcGISProject("CURRENT")` 在当前进程
是否可用（外部进程不可用是预期；Pro 进程内的 Python 窗口/Notebook 才可用）。
探针结果必须完整回传给用户/维护者，不得据此自行扩展动作。

### 实时桥（live/，操作 Pro 里当前打开的工程）
启动与工具清单见 `live/LIVE.md`。要点：桥跑在 Pro 进程内，经本机
127.0.0.1:47616 + 随机 token 与 MCP 服务端通信；12 个工程工具 + ping；
写类工具（add_layer_from_path、save_project）须 confirm=true，
confirm 只能在用户明确同意后填入。首次实机使用前先跑 `live/selftest.py`，
再按 `docs/CALIBRATION.md` 逐项校准。

## 安全纪律（硬规则，违反即停）

1. **原件只读**：禁止对用户指定的原始工程执行任何 save / 写入 / 删除动作。
   需要修改时，先 backup，再复制出一份工作副本，只改副本，并在回报中写明副本路径。
2. **禁止删除**任何图层、表、数据源；禁止批量改属性数据。v0.1 无头桥没有写动作，
   实时桥的写动作只有加数据与保存两项且带 confirm 闸；遇到清单之外的需求，
   停下回报，不要临时写脚本凑，更不要找任意代码执行通道绕过桥。
3. **GUI 占用**：工程正在 Pro 中打开时，无头 inspect 看到的是存盘状态（见上）；
   不要为了让 inspect "看到最新状态"就擅自让用户保存或替用户保存。
4. **许可/版本错误即停**：许可报错、arcpy 与 Pro 版本不匹配时，停下回报
   原始报错全文，不许换版本、换环境反复试（最多按报错表处置一次）。
5. **环境隔离**：不许往 `arcgispro-py3` 或任何既有项目环境里装包、改配置。
6. **路径含中文/空格**一律用引号包裹并按原始字符串传参；JSON 输出保持 UTF-8 不转义。
7. 每一步的脚本原始输出（JSON）都要留档回传；失败也要回传，不许只报结论。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `ARCPY_NOT_AVAILABLE` | 当前解释器没有 arcpy（用错了 Python） | 按 preflight 回报里的 python_candidates 换 Pro 自带 Python 或 propy 重跑；不要 pip 安装 |
| `FILE_NOT_FOUND` | 工程文件路径不存在 | 核对路径原文（中文/空格引号）后重跑 |
| `OPEN_PROJECT_FAILED` | 打开 .aprx 失败：许可未登录/被占用/工程损坏都可能 | 先请用户在 Pro 里确认已登录许可并能正常打开该工程；再用 backup 副本重试一次，仍失败则停 |
| 打开工程报许可相关 RuntimeError | Pro 未登录或许可服务不可用 | 停。请用户在 Pro 里完成登录后重跑 preflight |
| inspect 里大量图层 is_broken=true | 数据源被移动/改名，连接失效 | 如实写入回报，这正是盘点要发现的问题，不要自动修复 |
| 实时桥 discover 的 mode=file-fallback | 没拿到进程内当前工程，走的是文件回退 | 如实回报，不许说成实时接入；按 CALIBRATION.md 第 1 步排查 |

## 回报格式

每次动作后回报：①一句话结论；②脚本 JSON 原文；③若动过文件，列出新建文件路径清单。
没有 JSON 的回报视为未执行。汇报 inspect 结果时必须注明"此为已保存状态，
不含界面未保存修改"。
