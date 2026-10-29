# 实机校准指南 —— PostGIS 消费侧只读桥 v0.1 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述
要达成的结果、验收标准与红线，具体做法由执行者决定；但每一步的
原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

前置环境：一台装好 PostgreSQL + PostGIS 的机器，一份已知内容的
空间表（行数、范围可独立量算），一个**只读**数据库用户。校准机
上先跑通 `live/selftest.py`（协议自检 13/13）再进入实机步骤——
自检不过，先修协议层，不许往下走。

## 目标结果（全部达成才算完成）

1. probe_api.py 在目标库全绿：PostGIS 版本落档，SELECT 1 通过，
   允许表的 geometry_columns 登记与实际表结构一致（ready=true）。
2. 结构对账通过：list_spatial_tables 的几何列（列名/类型/SRID）
   与 `geometry_columns` 原始查询、table_columns 与
   information_schema 原始查询逐项一致。
3. 数值对账通过：table_summary 的 row_count 与独立
   `SELECT count(*)` 一致；extent 与独立 ST_Extent 查询（或在
   QGIS 里量算的范围）一致到浮点表示差异以内。
4. 导出对账通过：导出文件能在 QGIS 打开，几何与表内要素一致，
   features 数 = min(limit, row_count)；属性不含几何列本身
   （to_jsonb 已剔除），其余属性齐全。
5. 负例口径成立：空表 summary 回报 extent=null 并注明；只读
   用户下六工具全通；不存在的几何列被 GEOM_NOT_FOUND 拒绝；
   多个几何列未指定时被 AMBIGUOUS_GEOM 拒绝。
6. 校准结论回写 README「状态声明」：环境与版本、逐项结果、与
   模板的差异点；selftest 保持全 PASS。

## 校准顺序（不要跳步）

1. **连通与版本**：配好 PG* 环境变量与 POSTGIS_ALLOWED_TABLES，
   跑 probe_api.py 并完整回传 JSON。ready 不为 true 就停在这里，
   先解决连接/扩展，不许往下走。
2. **结构对账**：用你自己的客户端直接查 geometry_columns 与
   information_schema（参照值不许经桥产生），与桥的
   list_spatial_tables / table_columns 逐项核对。
3. **数值对账**：独立跑 count(*) 与 ST_Extent 查询，与
   table_summary 逐项对；浮点范围注意 psql 文本表示与 JSON
   数值的表示差异，按数值比对而非字符串比对。
4. **导出对账**：同一张表跑 export_geojson（小 limit），在
   QGIS 里加载：图层能渲染、要素数与属性与表内一致；再用
   大于行数的 limit 跑一次，确认 features 数封顶在实际行数。
5. **负例验证**：空表、无登记的几何列名、多几何列表不指定
   geom、允许集合外的表名，四种情况逐项确认报错口径如实，
   并回传原始 JSON。
6. **收紧与回归**：若目标 PostGIS 版本下模板有差异
   （geometry_columns 视图口径、to_jsonb 对几何列的表示、
   ST_Extent 空集行为等），先记录差异原文，再改模板或文档；
   跑 selftest；把改动点逐条列清回传。

## 红线

- 校准全程只许只读查询；不许为了让模板跑通去改表结构、加列
  或灌数据。样本数据须在桥调用之外准备并说明来源。
- 密码只经环境变量或 ~/.pgpass，不许出现在任何回传、日志或
  文件里。
- 对账参照值必须来自桥之外的独立来源；拿桥自己的输出对账
  等于没校准。
- 任一步对不上：停在该步、回传差异，不许改判定口径凑绿。
