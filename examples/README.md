# 示例总入口

第一次接触本仓，建议按这个顺序走：

1. **先看包清单**：`python scripts/quickstart.py --list`
2. **先跑一个离线自检**：`python scripts/quickstart.py --package qgis --selftest`
3. **不用装 GIS 先盘点样本工程**：`python scripts/quickstart.py --sample-qgis`
4. **生成某个包的客户端配置片段**：
   `python scripts/quickstart.py --package qgis --print-config`
5. 再进入具体包，读它的 `README.md`、`SKILL.md` 与 `docs/CALIBRATION.md`。

各包自己的配置片段与提示词仍在 `<package>/examples/`；本目录提供跨包
的样本数据与第一次试用路径。客户端配置文件落点见
[`docs/CLIENTS.md`](../docs/CLIENTS.md)，常见报错见
[`docs/TROUBLESHOOTING.md`](../docs/TROUBLESHOOTING.md)。

`sample-data/` 全部是合成样本，不证明实机校准。
