# 实战经验：用 arcmap 包完成 lab5 空间要素编辑（2026-10-28）

- 场景：中山大学《GIS 原理》上机实验五，用 ArcGIS Desktop 10.8 + arcpy 在
  无 GUI 条件下完成「图形编辑 / 打断融合 / 属性编辑 / 拓扑检查」四类任务，
  产出 mxd + shp + gdb + Word 报告。
- 环境：`C:\Python27\ArcGIS10.8\python.exe`（py2.7.16）、Desktop 10.8、
  ArcInfo 许可 Available、无网络 pip、无 GUI 交互（全靠脚本），
  PowerShell 5.1 作为外层 shell，py3 解释器单独用于渲染与文档生成。
- 结论先行：**桥的三件只读动作（preflight/backup/inspect）完全够用且零事故；
  真正的时间黑洞全部集中在「py2 编码」「arcpy 10.8 的 API 边角」和
  「无头环境没有的眼睛」这三件事上。**

下面按「现象 → 根因 → 处置」记录，每条都在本机实测命中过。

---

## A. 编码与路径（最高频，占本次阻塞的一半）

### A1. arcpy 不接受含中文的工作路径

- 现象：`arcpy.FeatureToLine_management(r'E:\ds工作区\...\Roads.shp', ...)` 报
  `IOError: [Errno 2] No such file or directory: 'E:\\ds\\xe5\\xb7\\xa5...'`，
  路径里每个中文变成了 `\xe5\xb7\xa5` 这样的裸字节。
- 根因：py2 下 arcpy 用 `mbcs`（GBK）打开路径，而调用方传进来的是 UTF-8 字节串；
  多字节被逐字节当 GBK 解释，路径必然不存在。父目录名（`ds工作区`）也会污染。
- 处置（已验证有效）：**把所有 arcpy 工作搬到纯 ASCII 目录**（本例 `C:\lab5work`），
  原件只读复制进去，成果用 py3 / PowerShell 再复制回中文路径。
  只要进入 arcpy 的路径全 ASCII，后面所有动作都不再出现此类错误。
- 反例（不要做）：给路径做 `_dec()` 解码补救。桥里的 `_dec()` 是为 `sys.argv`
  服务的；脚本内部自己拼的路径仍有同样的坑，逐个打补丁不如换目录。

### A2. py2 打印/写日志中的中文

- 现象：`print(u'...中文...')` 抛 `UnicodeEncodeError: 'ascii' codec can't encode...`。
- 处置：日志函数内部 `print('[log] ' + m.encode('utf-8'))`；
  写日志文件一律 `io.open(path, 'w', encoding='utf-8')`（内置 `open` 在 py2 不认 encoding）。

### A3. `sys.argv` 是 GBK 字节串（SKILL.md 已记，本次再次命中）

- 现象：传中文 .mxd 路径，arcpy 报 `ERROR 000732 ... does not exist`。
- 处置：确认桥的 `_dec()` 生效；自写脚本若直接读 argv，必须按
  UTF-8 → `sys.getfilesystemencoding()`/mbcs/gbk → latin-1 逐级尝试。

### A4. PowerShell 不能内联长中文 Python 代码

- 现象：`pwsh -c "& $py -c \"...中文...\""` 反复 `ParserError`（引号/中文被吞）。
  bash 风格 heredoc（`<<'EOF'`）在 PowerShell 里更是直接报错。
- 处置：所有脚本先落到文件（编辑器/写文件工具），再 `& python.exe file.py` 执行。
  一次内联都不要试，省下的时间远超写文件的成本。

---

## B. arcpy 10.8 的 API 边角（每一条都真的会拦路）

### B1. 进程内第一次 `SearchCursor(SHAPE@)` 会失败

- 现象：新进程第一次 `arcpy.da.SearchCursor(shp, ['SHAPE@'])` 报
  `RuntimeError: cannot open 'C:\lab5work\out\shp\Roads.shp'`；同一进程再跑就正常。
- 处置：脚本开头做 warm-up：`for _ in range(5): try: 试读一次; break; except: pass`。

### B2. `DeleteFeatures_management` 在 10.8 只接受一个参数

- 现象：`arcpy.DeleteFeatures_management(lyr, 'where')` 报参数个数错误。
- 处置：先 `MakeFeatureLayer` + `SelectLayerByAttribute`，再
  `arcpy.DeleteFeatures_management(lyr)`（图层选择集即删除范围）。

### B3. 文本字段写 `None` 直接失败

- 现象：`uc.updateRow([oid, None, area, shp])` →
  `RuntimeError: The field is not nullable. [Name]`。
- 处置：写 `''`。数值字段写 `None` 没问题，文本字段不行。

### B4. 迁移/新建要素类的 OID 字段名不一定是 `OBJECTID`

- 现象：在 `Check_Topography.gdb` 里用 `'OBJECTID IN (24,25,26)'` 做删除条件，
  删到的不是目标要素。该要素类同时有 `OBJECTID_1`（真 OID）与用户字段 `OBJECTID`。
- 处置：**永远先取** `oid_fld = arcpy.Describe(fc).OIDFieldName`，再用它拼 where。

### B5. 拓扑数据集用 `ListDatasets('', 'Topology')` 找不到

- 现象：拓扑明明建成功（`CreateTopology` 不报错、`ValidateTopology` 无错误），
  但 `arcpy.ListDatasets('', 'Topology')` 返回空，甚至返回 `None` 导致
  `TypeError: 'NoneType' object is not iterable`。
- 根因：拓扑挂在要素数据集内部，不在 gdb 根级。
- 处置：用
  `for dirpath, _, files in arcpy.da.Walk(gdb, datatype='Topology'): ...`
  能拿到 `<gdb>\Roads_buildings\Roads_buildings_Topology`。
  交付验收时也用 Walk，不要用 ListDatasets。

### B6. `ExportTopologyErrors` 在本机永久失败

- 现象：`ERROR 999999: Error executing function. Failed to execute (ExportTopologyErrors).`
  换空目录、删拓扑重建都无效。
- 处置：放弃该工具，改**几何解析自查**（本次实现，可直接复用）：
  - Roads 交叉：所有线段两两求交，交点在两条线内部 → crossing；只有一条线内部 → T-junction；
  - Buildings_bou 悬挂：把全部端点按 1.5 m 聚类，簇大小 == 1 即悬挂；
  - Buildings 重叠：两两 `polygon.union()` 后面积 > 阈值（如 1 m²）即重叠，并给出重叠面积。
  修正后再跑一遍同样的解析，用「crossings=0 / dangling=0 / overlaps=0」作为证据。

### B7. `FeatureToLine` 会产生零长碎段

- 现象：6 个要素打断出 28 段，其中 2 段长度 < 2 m（原线在交点附近回折造成）。
- 处置：打断后先按 `shape.length < 2` 过滤删除，再进入分类/融合，否则
  Dissolve 结果里会带脏段、长度统计偏差。

### B8. Dissolve 之后字段全丢

- 现象：融合出的 `Roads_three.shp` 只有 `FID/Shape`。
- 处置：Dissolve 之后重新 `AddField` + `UpdateCursor` 写 `Name`（road1/2/3）与
  `Length`（`shp.length`，注意 updateRow 的字段与值个数必须严格一致）。

### B9. `arcpy.mapping.Layer(path)` 要求文件真实存在

- 现象：`AddLayer` 报 `Object: CreateObject Layer invalid data source`。
- 根因：`Roads_three.shp` 落在 `out\`，而脚本拼的是 `out\shp\`。
- 处置：AddLayer 前 `assert os.path.exists`；把成品图层与其引用的数据放同一目录，
  打包时一起带走。

### B10. `replaceDataSource` 指向 gdb 要素数据集会失败

- 现象：`lyr.replaceDataSource(gdb\ds, 'FILEGDB_WORKSPACE', 'Roads')` →
  `Layer: Unexpected error`。
- 处置：改用「RemoveLayer 掉旧 shp 图层 + `AddLayer(df, arcpy.mapping.Layer(gdb\ds\fc), 'TOP')`」重建；
  或把 mxd 直接指向 `FILEGDB_WORKSPACE` 的要素类路径。

### B11. 交付 mxd 必须开相对路径，且数据同构摆放

- 处置（本次交付件做法，建议固化为标准动作）：
  1. 目录结构：`<包>/Map.mxd` + `<包>/shp/*.shp` + `<包>/<影像>.tif` + `<包>/<名>.gdb`；
  2. 图层重指向到**包内**路径：矢量用 `SHAPEFILE_WORKSPACE`，
     gdb 用 `FILEGDB_WORKSPACE`，**栅格必须用 `RASTER_WORKSPACE` + tif 文件名**；
  3. `mxd.relativePaths = True` 再 `saveACopy`；
  4. 重开验证：`ListLayers` 打印每个图层的 `dataSource`，逐条 `os.path.exists` 通过才算完。
- 只做其中一半（比如只开相对路径但栅格没重指向）会留下隐藏的绝对路径断链。

### B12. 无头下也能设置标注

```python
lyr.showLabels = True
lyr.labelClasses[0].expression = '[Name]'   # 字段名用方括号
lyr.labelClasses[0].showClass = True
```

---

## C. 无头环境没有的「眼睛」——本次最影响正确性的部分

### C1. `ExportToPNG` 渲不出真彩色（SKILL.md 已记，本次未再尝试）

结论不变：报告/成果图不要指望它。本次全部改用 PIL 自绘：把解码后的影像当底图，
再叠加 shp 要素，输出「编辑前/编辑后」「三条道路」「三栋建筑」「拓扑修正前后」对比图。

### C2. 16-bit tiled TIFF 需要自己解码

- 现象：交付影像 `中珠校区影像_ProjectRaster.tif` 是 16-bit RGB、tile 128、compression=1，
  Pillow 打不开，本机也没有 GDAL。
- 处置：手写 TIFF 标签解析（读 322/323/324/325 的 tile 信息、33550/33922 的地理参照），
  按 tile 解码拼成 `uint8` 数组（值域 0–255）。同时从 33550/33922 得到
  `PixelScale` 与左上角坐标，作为「像素 → 地图坐标」的换算依据。
- 收益：后续所有判读都在这张底图上做，坐标可反算，比在 ArcMap 里目测准得多。

### C3. shapefile 的 DBF 中文是 GBK

- 现象：py3 用 latin-1 读 DBF 得到 `Ö÷½ÌÑ§Â¥`。
- 处置：`raw.encode('latin-1').decode('gbk')`（try/except 兜底）。

### C4. 真值反推：docx 里的示范截图是可用的控制点源

- 教师在实验手册里内嵌了「校正前 / 建连接线 / 校正后」三张截图。
  把截图的矢量图层 bbox 与本地 shp 的 bbox 做最小二乘配准，即可把截图像素
  换算成地图坐标，从而**读出示范答案大概落在哪里**，再据此刻画目标多边形。
- 本次靠这一步才把「体育馆」的目标位置定在网球场东南的条纹屋顶建筑上，
  而不是凭印象猜。

### C5. 判读要靠网格 + 放大，不能靠缩略图

- 处置：写一个 `grid_view(extent, step=10)`，输出带 10 m/20 m 网格与坐标标注的
  影像裁片，人眼读点、脚本换算。10× 放大后仍模糊时，改用 4–6 px/m 的整体视图读轮廓，
  不要一味放大（放大不产生信息，只产生伪影）。

---

## D. 数据加工技巧（可直接复用的算法）

### D1. 用纯 Python 读写 shp 做几何诊断，比 arcpy 快且无编码坑

本次写了 `shpio.py`（读 .shp/.shx/.dbf，含多部件与环），在 py3 里做：
面积统计、端点悬挂距离、转角检测（`turn<65°` 即「结点异常偏移」）、
多边形重叠、连通分量。诊断定了再进 arcpy 执行编辑，避免来回试错。

### D2. 「空间校正」可用 Umeyama 相似变换无头复现

```python
# SVD 求 s,R,t，使 dst ≈ s*R*src + t
mu_s, mu_d = src.mean(0), dst.mean(0)
S = ((dst - mu_d).T @ (src - mu_s)) / len(src)
U, D, Vt = np.linalg.svd(S)
S_fix = np.eye(2)
if np.linalg.det(U) * np.linalg.det(Vt) < 0: S_fix[-1, -1] = -1
R = U @ S_fix @ Vt
s = np.trace(np.diag(D) @ S_fix) / ((src - mu_s) ** 2).sum() * len(src)
t = mu_d - s * R @ mu_s
```

- 结果要与 GUI 的 `Transformation-Similarity` 等价（本次 scale=1.035、rot=0.905°）。
- **残差大不等于做错**：原要素形状与真实地物不同形时，4 点最小二乘残差会有
  十几米，这与教师示范的「近似贴合」是同一种状态，如实写进报告即可。

### D3. 编辑脚本要「每次从只读原件刷新工作副本」

```python
for nm in ('Roads', 'Buildings', 'Water'):
    for ext in ('.shp', '.shx', '.dbf', '.prj'):
        shutil.copy2(os.path.join(SRC, nm + ext), os.path.join(WORK, nm + ext))
```
每次运行都从原件重新复制 → 脚本可反复重跑、结果幂等，出错不需要手工回滚。

### D4. 「打断后要分成几条」不能靠连通性

本次打断后 24 段只有 1 个连通分量（路网全连通），必须靠**走向/语义**分组：
用三条引导折线（从作业示意图反投影得到），按「线段中点最近的引导线」分类+BFS 传播。
教训：先确认「分组依据是什么」，再去写分组代码；否则会在连通性上白绕一圈。

---

## E. 仍然未解决 / 待验证

| 项 | 现状 |
|---|---|
| `ExportToPNG` 的真彩色问题 | 未解决，本次直接绕开（自绘）。若要做，建议先验证 Desktop 小版本对应的分辨率/色彩参数 |
| 后台线程调 arcpy 的稳定性 | 未测（本次全部串行前台执行） |
| `arcpy.Describe(topo)` 的属性名 | 不稳定（`featureClassNames` 等在本机取法不一致），改用 `da.Walk` + 几何解析证明 |
| `.gdb` 内拓扑随目录复制 | 已验证可行：整目录 `copytree` 后 `da.Walk(datatype='Topology')` 仍能找到拓扑 |

---

## F. 建议进 SKILL.md / PLAYBOOK 的硬规则（本次总结）

1. **arcpy 工作目录必须纯 ASCII**，中文路径只作输入输出端点（复制进出）。
2. **OID 字段名一律 `Describe().OIDFieldName` 取**，禁止硬编码 `OBJECTID`。
3. **拓扑一律用 `da.Walk(datatype='Topology')` 枚举**，不要用 `ListDatasets`。
4. **`ExportTopologyErrors` 判为不可用**，拓扑验收用几何解析三件套（交叉/悬挂/重叠）。
5. **交付 mxd 三段式验收**：数据同构摆放 → 逐层 `replaceDataSource`（栅格用 `RASTER_WORKSPACE`）
   → `relativePaths=True` → 重开打印 `dataSource` 逐条确认存在。
6. **无头不出界面截图**：成果图自绘，并向用户明确「这不是 ArcMap 界面截图」。
7. **首次 `SHAPE@` cursor 打 warm-up**；**文本字段不写 None**；**DeleteFeatures 单参数**。
