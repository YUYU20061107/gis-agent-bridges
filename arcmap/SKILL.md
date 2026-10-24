# Skill: arcmap-bridge-lite（ArcMap 地图文档桥接，轻量版）

让 AI Agent 通过 Esri 官方 Python 包 **arcpy.mapping** 操作 ArcMap 地图文档
（*.mxd），而不是直接读写二进制文件。本 Skill 只提供有限、受控的动作；
动作之外的一切操作（改数据、改符号、删图层）一律禁止自行发挥。
本包为个人自用工具：ArcMap 已于 2026-03-01 被 Esri 退役（10.8.2 为最终版），
不要把它当成长期演进的产品对待。

## 版本基线（开发基线）

- ArcMap Desktop 10.x（Windows），自带 **Python 2.7**
  （`C:\Python27\ArcGIS10.x\python.exe`；64 位后台地理处理另有
  `C:\Python27\ArcGISx6410.x\python.exe`）；arcpy 随 Desktop 安装。
- 桥接脚本写在 Python 2.7 / 3.x 兼容子集上；在别的解释器里跑只会得到
  `ARCPY_NOT_AVAILABLE` 的结构化报错——那是预期行为，不是脚本坏了。
- 若本机实际版本与上述不符，先停下回报版本差异，不要硬跑。

## 运行前：环境发现（每个新会话先做一次）

1. 定位 Desktop 自带 Python：优先 `C:\Python27\ArcGIS10.*\python.exe`；
   找不到时用无头脚本的 preflight 回报里的 `candidate_pythons` 与
   `desktop_dirs` 字段确认。
2. 实时桥的 MCP 服务端用任意 Python 3 即可（它只做转发，不需要 arcpy）。
3. 运行预检（见下），预检不过不许进入任何业务动作。

## 动作清单（无头桥，仅此三项）

所有动作通过桥接脚本执行，脚本输出单行 JSON，必须原样附在回报里。

### 1) preflight —— 环境预检（只读，无副作用）
```
"C:\Python27\ArcGIS10.x\python.exe" scripts/arcmap_bridge.py preflight
```
回报：当前解释器版本与路径、多策略找到的候选 Desktop Python、
Desktop 安装目录、arcpy 是否可导入及其产品/版本。导入失败时退出码为 1
且 error_code 为 `ARCPY_NOT_AVAILABLE`，回报里带候选路径供改用正确解释器。

### 2) backup —— 备份地图文档（只读原件）
```
"C:\Python27\ArcGIS10.x\python.exe" scripts/arcmap_bridge.py backup <.mxd 路径>
```
在同目录生成 `<原名>.bak-<yyyymmdd-HHMMSS>.mxd` 副本并回报 sha256；
同名文件地理数据库文件夹（`<原名>.gdb`）会一并整体复制为同时间戳的
`.bak-<时间戳>.gdb`，回报文件数与总字节。**任何写操作之前必须先 backup，
且写操作只许作用于副本**（见安全纪律）。

### 3) inspect —— 工程盘点（只读）
```
"C:\Python27\ArcGIS10.x\python.exe" scripts/arcmap_bridge.py inspect <.mxd 路径>
```
脚本会先把 .mxd（及同名 .gdb）复制到临时目录再打开（原件零接触），
输出 JSON：文档路径/活动视图/页面大小、每个数据框的名称/范围/比例尺/
空间参考、图层名称/数据源/显隐/是否断裂、独立表视图。
输出标注 `mode=headless-saved-state`：无头只能看到已保存状态，
不许向用户表述成"当前界面里的样子"。拿不到的字段为 null 并在
`notes` 里说明原因，不许猜。

### 校准探针 probe_api.py（仅首次部署或版本变更时运行一次）
```
"C:\Python27\ArcGIS10.x\python.exe" scripts/probe_api.py [可选的 .mxd 路径]
```
输出本机 arcpy 版本与安装信息、arcpy.mapping 关键函数清单、
`MapDocument("CURRENT")` 在当前进程是否可用。探针结果必须完整回传，
不得据此自行扩展动作。

## 实时桥（一句话）

实时桥是另一条线：桥脚本在 ArcMap 的 Python 窗口里运行，MCP 工具清单与
启动方法见 `live/LIVE.md`，实机校准顺序见 `docs/CALIBRATION.md`。
注意：实时桥的 save_document 是写操作，confirm 纪律与本文件的纪律一致。

## 安全纪律（硬规则，违反即停）

1. **原件只读**：禁止对用户指定的原始 .mxd 执行任何 save / 写入 / 删除动作。
   需要修改时，先 backup，再复制出一份工作副本，只改副本，并在回报中写明副本路径。
2. **禁止删除**任何图层、数据框、表；禁止批量改属性数据。无头桥没有写动作，
   遇到需要写的需求，停下回报，不要临时写脚本凑；实时桥的保存只走
   save_document 且必须经用户当场同意。
3. **GUI 占用**：若 .mxd 正在 ArcMap 中打开，无头 inspect 操作的是临时副本
   不受影响，但回报必须说明盘点结果是已保存状态、可能落后于界面。
4. **许可/版本错误即停**：arcpy 导入触发许可校验，许可报错、版本不匹配时
   停下回报原始报错全文，不许换版本、换环境反复试（最多按报错表处置一次）。
5. **路径含中文/空格**一律用引号包裹并按原始字符串传参；JSON 输出保持
   UTF-8（控制台编码受限时脚本会自动退回 ASCII 转义，仍是合法 JSON）。
6. 每一步的脚本原始输出（JSON）都要留档回传；失败也要回传，不许只报结论。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `ARCPY_NOT_AVAILABLE` | 当前解释器没有 arcpy（多半用错了 Python） | 改用 preflight 回报的 candidate_pythons 里的 Desktop 自带 Python 重跑，不要 pip 安装 arcpy（装不上，它随 Desktop 分发） |
| `FILE_NOT_FOUND` | .mxd 路径不存在 | 核对路径原文，含中文/空格时加引号 |
| arcpy 导入时报许可类错误（如 License/NotInitialized 语义） | Desktop 许可不可用（许可服务未起/授权过期） | 停。请用户在 ArcGIS Administrator 里确认授权后重跑 preflight |
| 打开 .mxd 慢/图层大量 is_broken=true | 数据源被移动或网络盘断开 | 如实写入 inspect 结果，这正是盘点要发现的问题，不要自动修复路径 |
| `INSPECT_FAILED` 附 traceback_tail | 打开/枚举过程异常（如文件损坏、版本高于 Desktop） | 回报原文；可用 backup 副本再试一次，仍失败则停 |

## 回报格式

每次动作后回报：①一句话结论；②脚本 JSON 原文；③若动过文件，列出新建文件路径清单。
没有 JSON 的回报视为未执行。
