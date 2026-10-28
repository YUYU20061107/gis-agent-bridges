# 版本口径（Versioning）

本仓有三层版本，含义不同，不能互相替代：

| 层级 | 例子 | 含义 |
|---|---|---|
| 仓库 Release | `v0.6` | 某一时点整个合集仓的发布快照，包含当时各包状态与传播材料 |
| 包版本 | SuperMap 包 `v0.4`、QGIS 包 `v0.2` | 某个包的文档、脚本、工具面与校准进度的综合演进版本，写在根 README 软件矩阵和包 README 中 |
| MCP 服务端版本 | `serverInfo.version`，如 SuperMap live server `0.3.0` | 某个 stdio MCP 服务端程序自身的版本，由 `manifest/build_manifest.py` 实启读取并写入 `manifest/tools-manifest.json` |

因此，SuperMap 的「包 v0.4 / live server 0.3.0」不是笔误：v0.4 记录
的是无头桥、文件回退模式、工程生产手册与验收材料的整包演进；0.3.0
只记录 live MCP 服务端程序。若 live 服务端代码没有变化，它的版本
可以暂时不跟随包版本。

## 变更规则

- 工具新增、删除、改名或参数语义变化：至少提升对应包版本，并在
  根 `CHANGELOG.md` 记录；删除或改名还要写迁移说明。
- 只改文档、样本或校准记录：可不提升服务端版本，但包版本与
  CHANGELOG 应能反映重要变化。
- 仓库 Release 只在合集状态、包集合或重要校准结论发生变化时发布；
  Release 号不替代包版本。
- 校准状态不是版本：一个版本可以同时包含已校准、协议自检与未证实
  的不同模式，必须按根 README 与各包 `docs/CALIBRATION.md` 分开看。
