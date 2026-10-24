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

## 动作清单（无头桥）

所有动作通过桥接脚本执行，脚本输出单行 JSON，必须原样附在回报里。
v0.2 基线为三项只读动作（preflight / backup / inspect）；v0.3-lab2 增加三个
**受控写动作**（georef / mkvector / buildmxd），见下方「v0.3-lab2 增补」。

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

## v0.2 增补（一句话）

v0.2 新增只读盘点/迁移验收脚本 scripts/verify_project.py（盘点 .mxd 的
数据框/图层/表视图，--copy-to 复制工程与同名 .gdb 等伴生文件后对副本
重开盘点，问题记入 issues；无 arcpy 时结构化报错 ARCPY_NOT_AVAILABLE），
以及 ENGINEERING-PLAYBOOK.md 工程手册；无头桥三件动作与实时桥工具清单不变。

## v0.3-lab2 增补（受控写动作 + py2 两个坑，2026-10-25 实机验证）

安装位置：`<DSH skills 目录>\arcmap-bridge-lite\`，解释器
`C:\Python27\ArcGIS10.8\python.exe`。v0.3-lab2 在原三项只读动作之外新增三个写动作，
每个写动作都必须显式带 `--confirm-write`，否则只做计算与试运行、不落盘。
写动作的输出目录由调用方给定，脚本本身不删除任何已存在文件。

### 4) georef —— 一次多项式（仿射）配准 + 落盘
```
"...\python.exe" scripts/arcmap_bridge.py georef --image <影像> --points <控制点 json> \
    --out <输出目录> [--sr 4326] [--rectify] --confirm-write
```
控制点 json 形如 `{"pairs":[{"id":1,"pixel":[col,row],"map":[lon,lat]}, ...]}`。
纯 Python 解 6 个未知数（不依赖 numpy），输出 `coef_x{a0,a1,a2}`/`coef_y{b0,b1,b2}`、
逐点 `error_m`、`rms_m`、`max_m`、`pixel_size_m`，写 `.jgw` world file、
`<名>_geo.jpg`、`<名>_geo.tif`（含 34264 旋转项）、`--rectify` 时再出
`<名>_rectify.tif`（北向对齐，BILINEAR 重采样），并回报每个文件的字节数。

### 5) mkvector —— 由 JSON 生成 shapefile
```
"...\python.exe" scripts/arcmap_bridge.py mkvector --spec <图层 json> --out <输出目录> --confirm-write
```
spec 结构：`{spatial_reference, layers:[{name, geometry(Polyline|Polygon), fields,
features:[{coords:[[x,y],...], attrs:{...}}]}]}`；每层回写
`features_written`/`features_counted`（两者必须相等才可信）与 `.shp/.dbf` 字节数。

### 6) buildmxd —— 套模板组装 .mxd 并导出布局图
```
"...\python.exe" scripts/arcmap_bridge.py buildmxd --template <.mxd 模板> --layers a,b,c \
    --out <.mxd> [--extent xmin,ymin,xmax,ymax] [--export-png <png>] [--dpi 100] --confirm-write
```
先 `saveACopy` 到新路径再改，回报每层 `is_broken`、`scale`、输出字节数。

### 本机校准发现（照抄进任何新会话的回报里）
1. **py2 `emit()` 崩溃**：内容含中文时 `json.dumps(..., ensure_ascii=False)` 抛
   `UnicodeDecodeError: 'ascii' codec can't decode byte 0xef`。已修为
   `_to_text()` 递归转 unicode → `dumps(ensure_ascii=False).encode('utf-8')` →
   优先 `sys.stdout.buffer`，py2 写 bytes，全失败退回 `ensure_ascii=True`。
2. **py2 `sys.argv` 是 GBK 字节串**（不是 UTF-8）：按 UTF-8 解码会把中文路径解成乱码，
   arcpy 随后报 `ERROR 000732: Input Dataset or Feature Class ... does not exist`。
   已加 `_dec()`（UTF-8 → `sys.getfilesystemencoding()`/mbcs/gbk → latin-1 逐级尝试）。
3. **`Warp_management` 在本机不可用**：控制器点参数无论怎么写都报
   `ERROR 000735: Source Control Points: Value is required`。改用
   `ProjectRaster_management(<geo.jpg>, <out.tif>, sr, "BILINEAR")` 得到北向对齐结果。
4. **`arcpy.Describe` 在本机大面积残缺**：`Describe(raster).width/.meanCellWidth` 抛
   `AttributeError: DescribeData: Method width does not exist`，`Describe(shp).spatialReference`
   同样抛 `Method spatialReference does not exist`。替代做法：栅格行列数用
   `arcpy.GetRasterProperties_management(path, "COLUMNCOUNT"/"ROWCOUNT")`；矢量要素数用
   `arcpy.GetCount_management`；坐标系读 `.prj` 文本；范围读 `.shp` 文件头
   （偏移 32 起 shapeType<int，36 起 XMin/YMin/XMax/YMax 四个 <d 双精度）。
5. **无头 `arcpy.mapping.ExportToPNG` 会把 RGB 影像渲成蓝色单色调**
   （示例像素 (12,16,82)），用未动过的原始 JPG 复现同样现象 → 与本 Skill 无关，
   是本机 ArcMap 无头渲染的问题。**报告/成果图不要依赖 ExportToPNG 出真彩色**，
   改用自绘合成（PIL/Matplotlib），并如实向用户说明这一点。

## 实时桥（一句话）

实时桥是另一条线：桥脚本在 ArcMap 的 Python 窗口里运行，MCP 工具清单与
启动方法见 `live/LIVE.md`，实机校准顺序见 `docs/CALIBRATION.md`。
注意：实时桥的 save_document 是写操作，confirm 纪律与本文件的纪律一致。

## 安全纪律（硬规则，违反即停）

1. **原件只读**：禁止对用户指定的原始 .mxd 执行任何 save / 写入 / 删除动作。
   需要修改时，先 backup，再复制出一份工作副本，只改副本，并在回报中写明副本路径。
2. **禁止删除**任何图层、数据框、表；禁止批量改属性数据。无头桥的写动作只有
   georef / mkvector / buildmxd 三个，且必须带 `--confirm-write`、必须写在用户给出的
   新路径下（不许覆盖原件）；这三个动作之外的写需求，停下回报，不要临时写脚本凑；
   实时桥的保存只走 save_document 且必须经用户当场同意。
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
