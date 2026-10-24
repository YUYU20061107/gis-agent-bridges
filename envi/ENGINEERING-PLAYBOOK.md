# 工程文件生产手册（ENVI 无头版，适配版 v0.2）

本手册把 SuperMap 包 2026-10-24 实机校准沉淀的通用工程纪律，适配到
ENVI 无头桥（.hdr 纯 Python 盘点层 + idlpy 无头 ENVITask 任务层）。
ENVI 专属事实以 docs/CALIBRATION.md 的实机校准为准；本手册中标注
「待实机验证」的条目是迁移来的假设，不是已证实结论。

## 1. 原件只读，先备份、只改副本

- 任何处理前先留底：`scripts/envi_bridge.py backup <栅格或.hdr>`，
  回报里数据文件与 .hdr 两份副本都要有 sha256，才算备份完成。
- run_task / export 的输入指向备份副本、输出指向单独的工作目录；
  原始栅格与 .hdr 全程零接触，交付时用 sha256 复核原件未变。
- 禁止删除任何栅格或头文件；禁止批量覆盖既有结果文件。

## 2. 伴生文件完整性：头/数据文件对是命门

- ENVI 栅格是**文件对**：`.hdr` 头文件 + 同名数据文件（无扩展名或
  .dat/.img/.raw/.bin/.tif），缺一半就是残缺数据，backup 会直接拒绝。
- 复制/迁移时必须成对搬运；只复制 `.hdr` 会让盘点误报、只复制数据
  文件则盘点根本无从做起。迁移验收用 `scripts/verify_project.py
  --copy-to` 对副本重开盘点，核对文件对与大小。
- 矢量伴生数据同理：.shp 必须带齐 .shx/.dbf（及 .prj），
  verify_project.py 会把缺侧文件记入 issues。
- 盘点先行：处理任何栅格前先 inventory，确认 samples/lines/bands、
  data type、interleave 与 `size_matches=true`；大小不符先查明
  （截断、头被改、interleave 不符），不许带着疑问往下跑任务。

## 3. 相对路径风险

- .hdr 本身不记录数据文件的绝对路径，靠**同名同目录**约定配对；
  工程/任务参数里引用的栅格路径若是相对路径，换目录、换工作目录
  后可能默默指向别处或找不到。
- 迁移后不要只看“文件在”：用 verify_project.py 对副本重盘，
  确认每个 .hdr 仍能配上数据文件且字节数吻合，才算迁移成立。

## 4. 写后重读验证持久化（不信 API 返回，警惕假成功）

- ENVITask 的 Execute 不抛错 ≠ 结果正确：任务回报后必须重读产出——
  输出文件真实落盘、字节数 > 0、再用 envi_raster_info / inventory
  盘点出行列与波段，与预期逐项对上，才许说“执行成功”。
- 参数 set 要逐项核对 set_report：参数没应用上的静默失败，
  按失败如实回报，不许拿“任务跑完了”含糊过去（待实机验证：
  不同 ENVI 版本的参数大小写与 set 行为以校准结论为准）。
- 盘点层的 `size_matches=false` 是数据问题信号，不是工具故障；
  如实写入回报，不许自动“修复”头文件去凑绿。

## 5. GUI / 无头边界（本包仅无头）

- 本包**只有无头模式**：ENVI 没有官方支持的 GUI 会话附着通道，
  idlpy 启动的是新的 HEADLESS 会话（见 live/HEADLESS.md）。
- 绝不许把无头会话的执行说成“正在操作用户打开的 ENVI 窗口”；
  需要看着影像交互的工作，直接用 ENVI GUI。
- 会话只试启一次：许可/安装问题导致启动失败，记 `ENVI_NOT_AVAILABLE`
  如实回报，不反复重试撞许可墙。

## 6. 导出注意

- export_raster_subset 须 confirm=true，且输出必须是**新文件**、
  指向工作副本目录；导出后按第 4 节重读验证（落盘 + 盘点对账）。
- 仅 .hdr 模式下导出返回 `NOT_SUPPORTED_IN_HDR_MODE`，这是最终结果，
  不许拿本地计算冒充 ENVITask/ENVIRaster 的导出结果。

## 7. 迁移验收（交付前清单）

1. `scripts/verify_project.py <工程目录或.hdr> --copy-to <新目录>`，
   副本盘点 issues 为空或逐条有解释。
2. 每个栅格：samples/lines/bands、data type、interleave 与来源一致。
3. 每个文件对：`size_matches=true`；band names / wavelength 对得上。
4. .shp 系伴生文件齐全（.shp/.shx/.dbf）。
5. 原件 sha256 与备份时一致（原件全程未变）。
6. 任务层产出（如有）：按第 4 节重读验证的记录齐全。

## 8. 失败如实回报

- 没有 ENVI 就报 `ENVI_NOT_AVAILABLE`，没有 .hdr 就报 `HDR_NOT_FOUND`，
  探针/盘点的原始 JSON 原样附在回报里；失败也是结论，不粉饰、不编造。
- 许可报错即停，回报原文；不换环境反复试探。
