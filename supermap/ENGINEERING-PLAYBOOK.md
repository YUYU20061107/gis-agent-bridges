# 工程文件生产手册（iobjectspy 10.1 / iDesktop 10i 实战版）

本手册来自 2026-10-24 用本 skill 完成一次真实工程交付（配准结果 + 轨迹点线 + 三维场景）的实战，
覆盖“把原始数据做成可提交的工作空间 + 数据源”这一类任务。先读本手册，再写一次性脚本。

## 1. 进程与工作空间（最容易翻车的地方）

- 一个 Python 进程**同一时刻只有一个 Workspace 有效**。`ws.create()`、`ws.open()`、
  `ws.open_datasource()` 都返回**新对象**，必须接住返回值；打开另一个 Workspace 后，
  前一个会变成 disposed（`add_map` 报 ObjectDisposedError）。
- 在第二个 Workspace 上 `open_datasource()` 会把数据源挂到**当前活动工作空间**，
  从而污染正在构建的 smwu。构建进程里不要再打开源工作空间。
- 需要别的数据源里的几何/字段时：**先 dump 成 JSON，关掉，再单独跑构建**。
  dump 用 GBK/UTF-8 都行，读的时候用 `utf-8-sig` 或 `gbk` 回退。
- iobjectspy 会往 CWD 写 `iobjectspy.log`；CWD 不可写时要 `chdir` 到可写目录。

## 2. 复制 vs 重建

- 有现成结果（如旧版 Result.udbx）时**优先复制**：逐要素重建在几千顶点级别容易丢几何、
  丢样式，而复制能原样保留。
- 必须重建时：dump 源几何 → 建新数据集 → 逐要素 `append(Feature)` → 设 CRS →
  校验记录数、空几何数、顶点数。
- `append` 的几何 dict 若是 WGS84 经纬度，先把数据集 prj 设为 4326，导出/地图 bounds
  才是经纬度；忘了这一步会把平面坐标原样写进去（现象：地图 bounds 是 2403…10559）。

## 3. 坐标系统

- `PrjCoordSys.from_epsg_code(4326)`；`dataset.set_prj_coordsys(pc)` 与
  `datasource.set_prj_coordsys(pc)` 都要设。
- Map 对象**没有** `prj_coordsys` 属性；地图 XML 复用旧图即可继承坐标系统。
- 判断是否地理坐标：看 bounds 是否落在经纬度范围，而不是只看属性。

## 4. 地图

- `ws.get_map(name)` / `ws.get_maps()` 返回**副本**；改完必须 `ws.set_map(name, map)`
  才持久化。`add_dataset`、`set_visible`、`set_view_bounds` 都受此影响。
- 从旧地图 XML 建图：`ws.add_map(name, xml)`。XML 里已经有的图层**不要**再用
  `add_dataset` 加一遍，否则层数翻倍（现象：5 层变 10 层）。
- 加图层：`m.add_dataset(dataset, True)`，图层 caption 默认等于数据集名。
- 视图范围：`m.set_view_bounds(Rectangle(left, bottom, right, top))`，单位是地图单位；
  `Rectangle(Point2D, Point2D)` 在 10.1 会 TypeError，用 4 个数值构造。
- 导出：`m.output_to_file(path, image_size=(w, h))`；以文件真实字节数和看图为准。

## 5. 字段与属性

- **保留字**：`Date`、`DATE`、`date`、`datetime` 作为用户字段名会被拒
  （`java.lang.IllegalArgumentException: fieldInfo`）；`Time` 可以用。
  日期请用 `DateStr`（TEXT）存 ISO `yyyy-mm-dd`，并在交付说明里写清“Date 是保留字”。
- `FieldInfo.is_system_field` 是**方法**，必须 `f.is_system_field()`；字段类型是 `f.type`。
- 复制用户字段：`ds.create_field(FieldInfo(f.name, f.type, f.max_length))`；部分类型会失败，
  捕获后逐条记录，不要整体回滚。
- 改属性用 `Recordset`：`rs.seek_id(i)` → `rs.edit()` → `rs.set_value(name, v)` →
  `rs.update()`；读值前判断 None / 空串。
- 新建数据集后先 `create_field` 再写记录；写完刷新或重开校验。

## 6. 轨迹与点线

- 点：`GeoPoint(Point2D(x, y))`；线：`GeoLine()` + `add_part([Point2D...])`。
- `DatasetVector.get_geometries()` 返回 GeoJSON 风格 dict，坐标在 `["coordinates"]`，
  没有 `parts` 键；不要按旧习惯找 parts。
- 连续经度写法（>180°）保持原样，不要自动 ±360；二维平面地图被拉长属正常现象，
  三维球面场景显示正常。
- 轨迹线按表格行序（SmID）连成，未去重、未补点；点数与线顶点数应一一对应。

## 7. 交付前校验清单

1. 整目录复制到**新路径**重开两份工作空间（验收迁移性）。
2. 数据源数 / 数据集数 / 记录数 / CRS。
3. 地图层数与 bounds（是否经纬度范围）。
4. `scenes` 数、场景 XML 里的图层引用名、图层数。
5. 关键字段空值数（如 DateStr 空值 = 0）。
6. 导出 PNG 非空、内容合理。
7. 原件 mtime 全程未变。
8. zip 里文件齐全、可从 zip 直接打开。

## 8. 症状 → 处置速查

| 症状 | 原因 | 处置 |
|---|---|---|
| `create_datasource` 失败 | 目标目录已有同名 .udbx | 换新目录或先删目标（只删副本） |
| `Workspace has been disposed` | 打开了另一个 Workspace | 一个进程只留一个；先 dump 再重建 |
| 地图层数翻倍 | XML 已有图层又 add | 只给 XML 没有的数据集加层 |
| 改了地图没保存 | 操作的是 get_map 副本 | `ws.set_map(name, m)` |
| bounds 是 2403…10559 | 数据没设 4326 或坐标未变换 | 设 prj / 应用仿射变换 |
| `AttributeError: prj_coordsys` | Map 不暴露该属性 | 用地图 XML 或 dataset 的 prj |
| 字段 Date 建不上 | SuperMap 保留字 | 用 DateStr |
| 三维图层加载报 WrapjMObjects | 无头环境缺 realspace 原生库 | 走场景 XML 或 iDesktop GUI |
| 场景保存了但重开没有 | 只保存了场景没保存工作空间 | 两次保存都确认（见 SCENE-AND-GUI.md） |
