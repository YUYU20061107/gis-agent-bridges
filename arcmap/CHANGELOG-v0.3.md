# CHANGELOG —— arcmap-bridge-lite v0.3（回灌与续修，2026-10-25）

来源：DSH 在 ArcGIS Desktop 10.8 / Python 2.7.16 实机完成 lab2 流水线
后产出的魔改版 v0.3-lab2（见 CHANGELOG-v0.3-lab2.md）。本轮由 Muse
回收复核后回灌进维护树，并继续修同类问题：

- 采纳：scripts/arcmap_bridge.py 全量（py2 emit/argv 两修 + georef /
  mkvector / buildmxd 三个受控写动作）；SKILL.md 的 v0.3-lab2 增补节
  （安装路径已脱敏）；五条实机发现写入 docs/CALIBRATION.md 校准记录。
- 续修（同一编码隐患在其他文件的同类位置，lab2 未覆盖）：
  verify_project.py 的 emit 与 argv 解码、--json-out 写文件前转码；
  probe_api.py 的 .mxd 路径参数解码；live/inapp_bridge.py 的响应
  序列化（预防性，实时桥仍未实机校准）；mcp_server serverInfo 升 0.3.0。
- 未采纳：lab2-scripts/（课程作业流水线，含本机绝对路径与作业数据，
  属一次性工件，不进维护树；原件在鱼鱼处保留）。
- 定位修订：ROADMAP 已把无头桥写动作口径改为「以 v0.3 三个受控写
  为限」，其余写业务仍不做。
