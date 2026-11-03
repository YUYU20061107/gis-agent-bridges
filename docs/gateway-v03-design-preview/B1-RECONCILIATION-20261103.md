# B1 逐叶对账表（定级版，2026-11-03）

- 证据：鱼鱼上传的 `introspect-result.json` 原件（191,632 B；Python 3.5.4／iobjectspy 10.1.0.0；5 模块导入成功、含一层子模块共 5,051 条（模块,成员）对、663 个唯一成员名）。Muse 独立解析全量成员后与 `leaves-full.json` 的 16 条 SuperMap unverified 叶逐叶交叉。
- 证据等级：**文件读取＋独立解析**（高于执行方自报）。注意边界：本次验的是「接口名是否存在于 API 表面」，不是功能实测；坐实 ≠ 可执行，仍须写工具＋实机校准后才升格。
- 顺带更正：v1 施工单 B1 行写 V20「其余六式」有误——注册表实为 **七式**未验（intersect、union、difference、erase、identity、symdifference、update；clip 已 ok 不在内）。

## 对账结果（16 叶）

### 函数坐实 ×10（模块级同名/对应函数存在）

| 叶 | 原生函数 | 备注 |
|---|---|---|
| V24 gis_slope | `calculate_slope` | 另有 compute_point_slope |
| V25 gis_aspect | `calculate_aspect` | 另有 compute_point_aspect |
| V26 gis_hillshade | `calculate_hill_shade` | 脚本 hint 写 `hillshade` 子串漏检所致假阴性，全量复核存在 |
| V20/intersect | `intersect` | 另有 intersect_line、intersect_polyline |
| V20/union | `union` | |
| V20/erase | `erase` | |
| V20/identity | `identity` | QGIS 无此原生、SuperMap 有——D2 合成范围据此已缩小 |
| V20/update | `update` | 同上 |
| V20/symdifference | `xor` | 原生名不同、语义对应，登记时注记「原生名 xor」 |
| V08 gis_calculate_field | `update_attributes` | 另有 `Recordset` 类为配套路径；签名写工具时按 Help 定 |

### 接口面坐实·类级 ×2（无模块级函数，但类与配套类型齐全，实现走类方法/属性）

| 叶 | 证据 | 实现路径 |
|---|---|---|
| V14 gis_assign_projection | `PrjCoordSys`、`PrjCoordSysType`、`GeoCoordSys` 等类齐全 | 数据集坐标系属性赋值，写工具时查 Help 定法 |
| V15 gis_reproject | `CoordSysTranslator`＋`CoordSysTransMethod`、`CoordSysTransParameter` 类齐全，另有通用 `convert` 函数 | 坐标转换类方法，签名待查 Help |

### 待定 ×1

| 叶 | 情况 |
|---|---|
| V20/difference | 模块级无 `difference` 函数；SuperMap overlay 模式里 difference 与 erase 的关系需查 Help 的 OverlayMode 枚举（类成员不在本次 dump 内）——批 1 定：或与 erase 同义合并登记，或以 erase 实现并注记 |

### 仍未清 ×3（模块级确无对应函数，保留 unverified）

| 叶 | 情况与下一步 |
|---|---|
| V06 gis_add_field | 只有 `FieldInfo`/`FieldType` 等类，无建字段函数；疑为 DatasetVector 类方法 |
| V07 gis_delete_field | 全量成员无任何 delete* 函数（仅无关的 remove_map）；同上 |
| V12 gis_merge_datasets | 仅有网络数据集专用的 `append_to_network_dataset`，无通用合并函数；疑与类方法 append 同源 |

三叶共同下一步：二轮脚本下钻类方法（对 DatasetVector、Recordset、Datasource 等核心类做 dir(类)），排 12 月批 1，与 A 类数据集族施工同批。

## D5 附带对账（同批 dump 顺带核，非 B1 范围）

| 叶 | 结果 |
|---|---|
| V32 gis_validate_geometry（supermap） | **函数坐实**：`topology_validate` 存在（另有 topology_processing、topology_build_regions）→ 可转实现/校准 |
| V13 gis_append_dataset（supermap） | 未清：同 V12，仅网络专用 append，待类方法下钻 |
| V22 gis_spatial_join（supermap） | 未清：无空间连接函数；`JoinItem`/`JoinType` 为属性连接类。候选路径＝空间查询＋属性回填的网关合成，批 1 定 |
| V29 gis_field_statistics（supermap） | 未清：`grid_basic_statistics` 等为栅格统计，矢量字段统计无同名函数，待下钻 |

## 注册表侧待办（批 0/G3 时一并）

- `leaves-full.json` 中 V32 的 postgis／arcgis-pro／qgis 三叶 status 字段为空（抽取瑕疵），G3 打标时补正。
- 本对账的逐叶新状态以机器可读版 `b1-reconciliation.json` 为 v0.3 侧覆盖层；v0.2 原始数据文件不动。

—— Muse，2026-11-03
