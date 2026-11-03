# G3 变更日志 · 能力三级打标＋V32 瑕疵修复（2026-11-03）

- 执行：Muse 子代理，批 0 / G3 子项（依据 `V03-WORKLIST-V2-GENERALIZED-20261103.md` 的 R3 口径与 G3 条目）。
- 范围纪律：只改注册表，不改任何工具实现代码；**打标 ≠ 验证**——除 V32 三叶的空 status 补正外，未动任何叶子的 status，证据口径不变（B1 逐叶新状态仍以 `b1-reconciliation.json` 覆盖层为准）。

## 1. 改动文件

| 文件 | 改动 |
|---|---|
| `gateway-v03/leaves-full.json` | 全部 195 行新增 `tier` 字段；V32 三叶补正 status 并加注记（见 §3）。文件其余内容经与改前副本逐行比对：非 tier 差异**仅** V32 三行，无其他改动。格式保持原样（indent=1、UTF-8 原文、无尾随换行）。 |
| `gateway-v03/G3-TAGGING-CHANGELOG-20261103.md` | 本文件（新增）。 |

v0／v0.1／v0.2 本体、`code/` 内其他文件均未触碰（自检运行仅按其设计回写 `code/selftest-results.txt`）。

## 2. 打标口径与三级分布

口径（施工单 R3 ＋ 本子项判定依据）：
- **core**：动词语义属统一契约、在 ≥3 个后端有对应叶（跨平台通用语义）。status 不影响 tier——core 动词在某后端 not_supported 的叶仍为 core（其语义正是 D2 网关合成要补齐的对象）。
- **extended**：语义可通约到通用概念，但仅在 1–2 个后端落地，或属服务／传感等扩展面。
- **exclusive**：平台独有、无跨平台语义对应。拿不准的叶按子项纪律标 extended 并列入待裁决（§4），不臆断。

分布（按 `leaves-full.json` 实际行数计）：

| tier | 叶数 |
|---|---|
| core | **163** |
| extended | **32** |
| exclusive | **0**（唯一候选 V01/V02 通道叶 3 行暂置 extended 待裁决，见 §4） |
| 合计 | **195** |

逐动词：core ＝ V03（4）、V04（3）、V05（6）、V06–V14（各 4）、V15（8）、V16（9）、V17（6）、V18（4）、V19（8）、V20（28）、V21（4）、V22（7）、V23–V29（各 4）、V32（4）、V39（4）、V40（4）；extended ＝ V01（2）、V02（1）、V30（1）、V31（4）、V33（1）、V34（1）、V35（3）、V36（8）、V37（1）、V38（10）。

**账目差注记（既有差异，非本次改动引入）**：施工单与 v0.2 README 的总账为 198 叶（ok 157＋unverified 19＋not_supported 22），而 `leaves-full.json` 实际为 195 行，改前状态分布为 ok 151／unverified 19／not_supported 22／空 3——unverified 与 not_supported 两数与总账一致，差额在 ok 侧（6）与空 status（3）。本次未擅自增删行补账，差异原样保留，待批 1 账目刷新时一并核。

**与 B1 对账的对齐**（tier 与对账定级正交，仅记衔接点）：
- V20 supermap 七式（含 difference、symdifference）均为 core；difference 与 erase 同义合并、symdifference 原生名 xor 的注记以二轮对账为准，本次未改其 status／native。
- V22 supermap 叶为 core：空间连接属核心语义，其实现走网关合成是实现路径，不降 tier。
- V06／V07／V12／V13／V29 的 supermap 叶均为 core（类级坐实结论不影响 tier，其 status 仍以覆盖层为准，本文件未升格）。

## 3. V32 瑕疵修复

- 对象：`gis_validate_geometry` 的 postgis／arcgis-pro／qgis 三叶，改前 status／kind／native／bts 全空（抽取瑕疵，一轮对账已登记）。
- 修复：三叶 status 补为 **`unverified`**，并加 note 注明补正依据；kind／native／bts 保持空（与注册表中其他未落地叶的形态一致）。supermap 叶的 not_supported 未动。
- 取值理由（判断件，留痕）：同动词的 supermap 叶虽为 not_supported，但其注记明示那是「本波」针对 SuperMap 拓扑面的波次决定，且一轮对账已证该面函数坐实（`topology_validate`）——把这一波次决定复制到另外三个从未查验过的后端属于臆断；注册表中「未查验」的如实状态是 unverified（三叶在更早的 `leaves.json` 抽取中同为空值，亦无其他定级记录）。若批 1 决定按波次口径统一为 not_supported，此为一行之改，请裁决时明示。

## 4. 待人工裁决清单（1 项，涉 3 行）

| # | 叶 | 现标 | 争议点 |
|---|---|---|---|
| 1 | V01 gis_run_gp（arcgis-pro ok 叶、arcmap not_supported 叶）、V02 gis_run_processing（qgis ok 叶），共 3 行 | extended | 两解：①厂商算法宇宙通道（GP／Processing）无跨平台语义对应，应标 **exclusive**；②「经通道执行后端自有算法」是双后端共有的元语义，可标 extended。裁决后若取①，3 行改 exclusive，分布变为 core 163／extended 29／exclusive 3。 |

已定但附依据（非待裁决，供复核）：V33 矢量瓦片服务、V34 图层发布——语义本身通用（服务发布／瓦片供给），仅单后端落地，故 extended；V35 服务发现、V36 SensorThings 实体查询——服务面扩展语义可通约，extended；V30 空间过滤、V31 量测——通用语义仅 postgis 落地，extended；V37/V38 点云信息与处理——操作语义通用、仅 qgis（PDAL）一面落地，extended。

## 5. 自检结果

- 脚本：`code/selftest.py`（v0.3 代码副本离线自检，证据等级＝离线协议自检）。
- 改前基线：**148/148 通过，退出码 0**。
- 改后复跑：**148/148 通过，退出码 0**，无回归。
- 说明：该自检直读 `code/` 内注册表（gp/processing/verbs/templates），不读 `leaves-full.json`，故本次结果主要证明代码副本整体未受扰动；`leaves-full.json` 自身的完整性由 §1 的逐行比对（仅预期差异）另行保证。
