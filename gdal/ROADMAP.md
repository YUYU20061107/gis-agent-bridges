# ROADMAP —— GDAL/OGR 工具桥演进与待校准清单

## 定位前提

本包是固定模板的工具桥，不是 GDAL 的通用命令行代理：
探查三模板、转换两模板、PAM 强制关、只写新文件，这套
边界就是产品本身。演进方向：在这条窄缝里把真实 GDAL
各版本、各驱动下的解析与转换证据做扎实；扩格式要逐个
格式做实机对账，不许只改枚举就算支持。

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | stdio MCP 服务端 7 个工具（ping / discover 只读，raster_info / vector_info / raster_stats 只读探查，convert_raster / convert_vector 带 confirm 闸）；scripts/gdal_bridge.py 固定五模板（gdalinfo -json、gdalinfo -stats -json、ogrinfo -so -al、gdal_translate -of、ogr2ogr -f）＋本地路径校验（拒远程与 /vsi）＋GDAL_PAM_ENABLED 子进程强制 NO＋输出不存在/扩展名匹配/父目录存在三校验；token 守卫常开（无配置时生成随机 token 落文件 0600）；二进制路径 GDAL_BRIDGE_* 可覆盖；probe_api.py 环境探针；selftest 四假二进制替身协议自检 | VM 侧已验证（2026-10-29，Python 3.12.3）：py_compile 通过、selftest **15/15 PASS**、probe 如实回报四件工具皆无；**未实机校准**（无 GDAL 环境） |

## 待实机校准清单（按依赖顺序，工单全文见 docs/CALIBRATION.md）

1. **连通与版本**：真实 GDAL 上 probe_api.py 全绿，
   四件工具同版本落档。
2. **探查对账**：gdalinfo -json 与 ogrinfo 文本解析与
   原始输出逐项一致，多图层数据集逐层核对。
3. **零副作用实测**：raster_stats 前后原件目录清单与
   哈希不变、无 .aux.xml 新增。
4. **转换对账**：GTiff 副本与 GeoJSON 输出可开、尺寸/
   要素数一致；内容差异口径落档。
5. **负例与回归**：confirm 闸、OUTPUT_EXISTS、
   REMOTE_PATH_REJECTED、GDAL_FAILED 口径成立；按实机
   差异修正解析或文档，跑 selftest 保持全 PASS，把
   校准结论回写 README 状态声明。

## 候选后续（未立项，先过校准再谈）

- 格式扩充须逐个过实机对账：候选栅格侧 COG（注意 COG
  涉及创建选项，与“无选项透传”的边界冲突，须先重新
  评审模板设计再议）、矢量侧 Shapefile（多文件数据集
  的输出存在性判定与目录语义要先设计）。
- 与 QGIS 包联动（探查后直接在 QGIS 打开）排在两包
  分别完成实机校准之后；与 grass-gis 包的导出复核
  联动同理，结论按各包证据口径分别认定。
- 老版本 GDAL 无 -json 时的文本回退解析：是否做、做到
  什么程度，先看校准落档的版本分布再定，不预先承诺。
