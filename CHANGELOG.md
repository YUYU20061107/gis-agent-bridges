# 变更记录（Changelog）

本文件记录合集仓层面的重要变化。包内细节见各包 `ROADMAP.md` 与
`docs/CALIBRATION.md`；版本层级关系见 `docs/VERSIONING.md`。
v0.6 之前的历史以 Git 提交与 GitHub Releases 为准。

## Unreleased

### Added

- 新增 pgRouting 消费侧只读包（5 个工具）与 istSOS / OGC
  SensorThings API 消费侧只读包（6 个工具），合集扩展为 11 包、
  95 个工具。
- 新增根级快速验证工具、合成样本工程、客户端接入指南、故障排查、
  版本口径、贡献指南与 Issue 模板。
- pgRouting 增加样本边表、Docker 起步环境与 live 说明；istsos 增加
  只读探针、工程手册与公开 STA 演示端点边界说明。

### Fixed

- CI 自检覆盖由 9 包扩展为 11 包。
- 补齐根 README 的获取方式、Python 版本矩阵、token 两种模式说明、
  许可证与 Glama 徽章，并澄清 SuperMap 包版本与服务端版本的区别。
- SECURITY 增加 pgRouting 数据库面与 istsos/STA 网络面的威胁说明、
  私密漏洞报告路径、受支持版本与响应目标，并提供英文版。

## v0.6 - 2026-10-27

- 发布九个桌面 GIS 桥包的合集版本：SuperMap、ArcGIS Pro、ArcMap、
  QGIS、GeoScene、MapGIS、ENVI、Global Mapper、FME。
- SuperMap 文件回退模式已在 iDesktop 10i 上完成实机校准；ArcMap
  无头桥已完成实机校准；其余能力按各包校准文档如实标注。
