# Skill: qgis-bridge（QGIS 工程文件桥接）

让 AI Agent 通过 QGIS 官方 Python 接口 **PyQGIS** 操作 QGIS 工程文件
（*.qgs / *.qgz），而不是直接读写工程文件内容。
本 Skill 只提供有限、受控的动作；动作之外的一切操作（改数据、改符号、删图层）一律禁止自行发挥。

## 版本基线（开发基线）

- QGIS 3.x（建议 LTR），Python 3.x。
- 若本机实际版本与上述不符，先停下回报版本差异，不要硬跑。

## 运行前：环境发现（每个新会话先做一次）

1. 运行 preflight（见下），看清本机可用的模式：
   `headless-file-parse` 恒可用（纯标准库解析，不需要 QGIS）；
   `headless-qgis` 需要能导入 qgis 模块的解释器（QGIS 自带 Python 或 OSGeo4W 环境）。
2. **不要使用或修改与本任务无关的既有项目环境**（不要为了装 qgis 去动别人的 conda 环境；
   需要 QGIS 的 Python 时用 QGIS 安装自带的解释器）。
3. 预检回报与预期模式对不上时，先停下回报，不要往下走。

## 动作清单（v0.1，仅此三项）

所有动作通过桥接脚本执行，脚本输出单行 JSON，必须原样附在回报里。

### 1) preflight —— 环境预检（只读，无副作用）
```
<python> scripts/qgis_bridge.py preflight
```
检查：Python 版本、qgis 模块可导入性与版本、qgis / qgis_process 命令、
常见安装位置线索，并回报 `ready_modes`（当前真正可用的模式清单）。

### 2) backup —— 备份工程文件（只读原件）
```
<python> scripts/qgis_bridge.py backup <工程文件路径>
```
在同目录生成 `<原名>.bak-<yyyymmdd-HHMMSS><扩展名>` 副本并回报 sha256。
同时回报同名数据目录是否存在、同名数据文件候选清单——那只是**提示**：
工程若用相对路径引用了同名数据，迁移备份时要自行一并带走，桥不会替你复制数据。
**任何写操作之前必须先 backup，且写操作只许作用于副本**（见安全纪律）。

### 3) inspect —— 工程盘点（只读）
```
<python> scripts/qgis_bridge.py inspect <工程文件路径> [--strategy auto|parse|qgis]
```
脚本会先把工程复制到临时目录再打开/解析（原件零接触），输出 JSON：
工程标题、画布 CRS、每个图层的名称/类型/数据源/提供者/CRS、图层树顺序与
显隐、打印布局名。策略说明：
- `parse`（headless-file-parse）：纯标准库解析 .qgs XML / .qgz 内的 .qgs，
  不需要 QGIS；拿到的是工程文件里记录的状态。
- `qgis`（headless-qgis）：用 QgsApplication 无头打开，由 QGIS 本体枚举，
  字段更权威（如图层 valid 性），但需要 QGIS 运行时。
- `auto`（默认）：qgis 可导入时用 qgis 策略，否则 parse 策略。
实际命中的策略记在输出的 `mode` / `opened_via` 字段里，回报时不许省略。
拿不到的字段为 null 并在 `notes` 里说明原因，不许猜。

### 只读盘点/迁移验收 verify_project.py（v0.2 新增）

python scripts/verify_project.py <工程文件路径> [--copy-to <新目录>]

纯 Python 解析盘点图层/数据源/CRS/图层树/布局，逐图层核对数据源文件与
shapefile 伴生件存在性，问题记入 issues；--copy-to 会复制工程、同主名
伴生文件与各图层本地数据源后再对副本盘点。全程只读，失败输出结构化
JSON 并退出码 1。迁移/交付验收按 ENGINEERING-PLAYBOOK.md 第 7 节执行。

### 校准探针 probe_api.py（仅首次部署或版本变更时运行一次）
```
<python> scripts/probe_api.py [工程路径]
```
输出本机 PyQGIS 的 QgsProject / QgsApplication / QgsMapLayer / QgsVectorLayer /
QgsLayoutExporter / QgsLayerTreeLayer 实际方法清单，以及当前进程里 iface 的值、
processing 模块可用性。探针结果必须完整回传给用户/维护者，不得据此自行扩展动作。

## 安全纪律（硬规则，违反即停）

1. **原件只读**：禁止对用户指定的原始工程执行任何 save / 写入 / 删除动作。
   需要修改时，先 backup，再复制出一份工作副本，只改副本，并在回报中写明副本路径。
2. **禁止删除**任何图层、数据源；禁止批量改属性数据。v0.1 无头桥没有写动作，
   遇到需要写的需求，停下回报，不要临时写脚本凑。
3. **GUI 占用**：若工程正在 QGIS 中打开并有未保存修改，无头 inspect 读到的是
   已保存状态，与界面不一致属正常现象，如实说明，不要强行处理。
4. **版本错误即停**：qgis 模块版本与目标工程版本差异过大、解析失败时，
   停下回报原始报错全文，不许换版本、换环境反复试（最多按报错表处置一次）。
5. **路径含中文/空格**一律用引号包裹并按原始字符串传参；JSON 输出保持 UTF-8 不转义。
6. 每一步的脚本原始输出（JSON）都要留档回传；失败也要回传，不许只报结论。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `FILE_NOT_FOUND` | 工程路径不存在 | 核对路径原文后重跑一次，仍失败则停 |
| `UNSUPPORTED_FORMAT` | 不是 .qgs/.qgz | 停，QGIS 工程只认这两种扩展名 |
| `QGIS_NOT_AVAILABLE` | 指定了 qgis 策略但 qgis 模块不可导入 | 改用 QGIS 自带解释器，或退回 parse 策略并如实说明 |
| inspect 里图层 `crs_authid` 为 null | 该图层在工程文件中没有记录 CRS | 如实回报，这正是盘点要发现的问题（无 CRS 图层），不要自动赋 CRS |
| inspect 里图层树为空但图层清单非空 | 工程文件的 layer-tree 节缺失或版本太旧 | 以图层清单为准并在回报中注明 |
| `INSPECT_FAILED` 附 traceback | 解析或打开失败（文件损坏/版本过新） | 回报原文；可换另一策略试一次，仍失败则停 |

## 回报格式

每次动作后回报：①一句话结论；②脚本 JSON 原文；③若动过文件，列出新建文件路径清单。
没有 JSON 的回报视为未执行。
