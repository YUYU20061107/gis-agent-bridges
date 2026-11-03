# B1 二轮对账（2026-11-03 晚）——B1 关账

输入：`introspect-r2-result.json`（11,396 B，WorkBuddy 以 `.venvs\sm35\python.exe`（Py 3.5.4＋iobjectspy 10.1.0.0）在 E:\ds工作区 只读执行 `introspect_iobjectspy_r2.py`，退出码 0，10 个类全部覆盖；Muse 独立解析全量）。原件存 `~/workspace/user/files/introspect-r2-result_6_ka36.json`。
证据等级：类成员存在性＝文件读取级（dir() 実測）；「坐实」仍指名字存在，**不等于可执行**——升格须写工具＋实机校准（批 1）。

## 二轮定级（7 项全清）

| 叶 | 结论 | 依据 |
|---|---|---|
| V06 gis_add_field | **类级坐实** | `DatasetVector.create_field` / `create_fields` / `append_fields` |
| V07 gis_delete_field | **类级坐实** | `DatasetVector.remove_field` |
| V12 gis_merge_datasets | **类级坐实（实现路径）** | `DatasetVector.append` 逐个追加实现；注记语义边界：append 要求 schema 兼容，合并前须校验字段结构 |
| V13 gis_append_dataset | **类级坐实** | `DatasetVector.append`（本义命中） |
| V22 gis_spatial_join | **定性关闭：无原生** | `JoinItem` 仅 join_filter/join_type、`QueryParameter.join_items` 均为属性连接，无空间连接原生函数 → 归 D2 网关合成（空间查询＋属性回填），批 1 实现 |
| V29 gis_field_statistics | **类级坐实** | `Recordset.statistic` |
| V20/difference | **与 erase 同义合并登记** | `OverlayMode` 枚举实测仅 7 值：CLIP/ERASE/IDENTITY/INTERSECT/UNION/UPDATE/XOR，**无 DIFFERENCE**——SuperMap 模型里 A−B 即 ERASE。至此 V20 七式全有原生落点（symdifference=xor 注记、difference=erase 注记） |

## B1 总账（关账）

- 16 叶：一轮定级 10 函数坐实＋2 类级坐实（V14/V15）＋V20 其余式；二轮补齐 V06/V07/V12 三叶类级坐实、V20/difference 定性。**16/16 全部定级，无悬空。**
- D5 附带四项：V32 函数坐实（一轮）、V13 类级坐实、V29 类级坐实、V22 定性为网关合成。**4/4 关闭。**
- 后续动作归批 1：上述类级坐实叶写工具＋实机校准后才升格 ok；V22 并入 D2 合成清单（PostGIS＋QGIS 之后第三个合成对象：SuperMap spatial_join）。
