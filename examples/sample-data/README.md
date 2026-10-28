# 样本数据（synthetic sample data）

这里的数据全部是为第一次试用准备的**合成样本**，不是实测数据，也不是
任何真实工程。它们只验证文件解析、协议路径与样本工作流，不证明任何包
已完成实机校准。

## QGIS 最小样本

目录 `qgis/` 内有：

- `minimal-project.qgs`：只含一个矢量图层的最小 QGIS 工程；
- `layers/stations.geojson`：3 个合成站点点位。

不需要安装 QGIS 就可以先验证无头解析：

```bash
python scripts/quickstart.py --sample-qgis
```

预期：报告能识别工程标题、EPSG:4326、1 个图层与数据源
`./layers/stations.geojson`。若要在 QGIS 中打开，请打开样本目录的
**副本**，不要把样本当成真实工程继续生产。

## pgRouting 样本

可直接试的样本边表与 Docker 起步环境在
[`pgrouting/examples/`](../../pgrouting/examples/)：样本图、建表 SQL、
预期最短路径和校准边界都写在该包文档中。样本预期值由图上成本人工
核算，不是由桥反推。

## SensorThings 样本

istsos 包的离线自检自带假 STA 服务端；公开演示端点的使用边界见
[`istsos/README.md`](../../istsos/README.md)。公开 FROST/OGC 演示服务
是其他 STA 实现，只能证明 SensorThings 协议路径，不是 istSOS4 本体
校准。
