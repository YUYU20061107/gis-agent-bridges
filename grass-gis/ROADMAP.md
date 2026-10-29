# ROADMAP —— GRASS GIS 无头桥演进与待校准清单

## 定位前提

GRASS GIS 没有 GUI 会话附着通道，本包永远只做无头批
处理：固定模板调用 --exec。不做任意模块执行、不做实时
桥、不进 GRASS 主仓当组件。演进方向只有一个：在固定
模板这条窄缝里把作业覆盖与校准证据做扎实，且每加一个
作业都要先过同样的安全评审（参数角色、覆盖保护、区域
语义）。

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | stdio MCP 服务端 7 个工具（ping / discover / location_info / list_maps / raster_info 只读，run_module / export_vector 带 confirm 闸）；scripts/grass_bridge.py 固定六模板（g.list / r.info / v.out.ogr ＋ r.slope.aspect / r.relief / r.resample 三作业）＋名字/路径双重校验＋永不传 --overwrite＋导出只写新文件；gisdbase 只从环境变量读；token 守卫常开（无配置时生成随机 token 落文件 0600）；probe_api.py 环境探针；selftest 假 grass 替身协议自检 | VM 侧已验证（2026-10-29，Python 3.12.3）：py_compile 通过、selftest **15/15 PASS**、probe 如实回报无 GRASS；**未实机校准**（无 GRASS GIS 环境） |

## 待实机校准清单（按依赖顺序，工单全文见 docs/CALIBRATION.md）

1. **连通与版本**：真实 GRASS 上 probe_api.py 全绿，
   版本与 location 清单落档。
2. **只读对账**：g.list / r.info 与桥回报逐项一致；
   location_info 与 g.proj、g.region -p 的口径差异
   落档。
3. **作业对账**：slope_aspect 在已知 DEM 上数值抽查
   与直接命令行结果一致；区域口径写清。
4. **覆盖保护实测**：重名输出必须失败且原图层未变。
5. **导出对账**：GeoJSON 在 QGIS 打开，要素数与
   v.info 一致。
6. **负例与回归**：confirm 闸、BAD_JOB、GRASS_FAILED
   口径成立；按实机差异修正解析或文档，跑 selftest
   保持全 PASS，把校准结论回写 README 状态声明。

## 候选后续（未立项，先过校准再谈）

- 作业扩充须逐条过同样的安全评审：候选如 r.univar 类
  只读统计（可议降为只读工具）、v.buffer / r.buffer
  类缓冲作业（输出新图层）；每个新作业都要有对应的
  实机数值对账与覆盖保护验证，不许只加模板不加校准。
- 区域（region）目前只读不改：是否提供“显式指定区域
  跑作业”须先设计口径（作业级临时区域、不动 mapset
  WIND），过评审后再议。
- 与 gdal 包的联动（导出 GeoJSON 后用 gdalinfo 复核）
  排在两包分别完成实机校准之后，结论按各包证据口径
  分别认定。
