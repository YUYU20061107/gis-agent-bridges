# 实机校准指南 — envi-bridge（ENVI 无头版）

适用前提：一台装有正版 ENVI + IDL 并有可用许可的机器；
Python 解释器能 `from idlpy import IDL`。校准全程在**数据副本**上做，
顺序不可跳：先盘点对账，再启会话，最后才许在副本上 run_task。

## 第 0 步：准备

- 选一个小型已知栅格（最好自带 .hdr 且你知道它的行列数/波段数/传感器）。
- 用脚本留底：
  ```
  <python> scripts/envi_bridge.py backup <栅格或.hdr>
  ```
  验收：回报里数据文件与 .hdr 两份副本都有 sha256。

## 第 1 步：.hdr 盘点对账（不需要 ENVI 许可）

```
<python> scripts/envi_bridge.py inventory <样本栅格所在目录>
```
验收标准：
- [ ] samples / lines / bands 与 ENVI 里打开该栅格看到的一致；
- [ ] data type 与 interleave 与文件属性一致；
- [ ] band names / wavelength（若有）逐项对得上；
- [ ] `size_matches` 为 true；为 false 时先查明原因（截断/头被改），
      未查明不许进入下一步并须在回报中记录。

## 第 2 步：idlpy 启动与版本对账

```
<python> scripts/probe_api.py
```
验收标准：
- [ ] .hdr 解析自检 ok；
- [ ] ENVI session started: ok（失败＝许可或安装问题，停，按 SKILL.md
      报错表处置，不许反复重试）；
- [ ] ENVI / IDL 版本已抄录进回报；
- [ ] ENVITask 名单抽样有输出，并记下命中的枚举策略名（via）。

## 第 3 步：list / describe 对账（只读）

经 MCP（先跑 `live/selftest.py` 确认协议层 6/6 PASS 并恢复原 token 设置），或在
装有 idlpy 的 Python 里直接对照 MCP 工具逻辑：

- [ ] envi_list_tasks 的名单与 probe 抽样一致（同 via 策略）；
- [ ] envi_describe_task 对 2 个已知任务的参数名单，与 ENVI 官方任务
      文档逐项核对，差异（缺项/多项/命名大小写）逐条记录。

## 第 4 步：副本数据上 run_task（唯一的写步骤）

- 选一个无害任务（如对副本做波段运算/指数计算），**输入指向第 0 步的
  备份副本，输出指向单独的校准输出目录**，由用户当场确认后带
  confirm=true 执行。
- 验收标准：
  - [ ] 回报 JSON 中 `executed: true` 且 via 字段非空；
  - [ ] 参数 set 报告与预期一致（没有 param 未应用的静默失败）；
  - [ ] 输出文件真实落盘且字节数 > 0，并能被 envi_raster_info 盘点出
        正确的行列/波段；
  - [ ] 原始栅格与 .hdr 的 sha256 与第 0 步回报一致（原件零接触）。

## 第 5 步：收尾收紧

- 把第 2、3 步命中的策略（任务名枚举、参数大小写、describe 字段）
  回写进 `live/mcp_server.py` 与 probe 的注释，注明实机 ENVI/IDL 版本。
- 复跑 `live/selftest.py` 与第 1 步 inventory，确认收紧后无回归。

## 红线

- 校准只用副本数据；任何一步都不许对原件跑 run_task。
- confirm 只能在用户当场点头后填 true，不许为"把校准跑完"自填。
- 许可报错即停并回报原文；不许换机器、换解释器反复撞许可墙。
- 哪一步对不上账，停在哪一步，如实记录差异，不要临时改判定标准凑绿。

## 回报格式

按步回报：①每步的原始输出（JSON 或探针全文）；②命中的策略名（via）；
③差异清单（预期 vs 实测）；④实机 ENVI/IDL 版本号。缺原始输出的步骤
视为未校准。
