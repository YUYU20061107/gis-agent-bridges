# ENGINEERING-PLAYBOOK —— GRASS GIS 无头桥部署与验收手册（简版）

本包结构简单（stdio 服务端＋grass 子进程），手册只列
部署与验收的硬清单；原理与口径以 README / SKILL.md 为准。

## 部署清单

1. Python 3.x 可用，`grass` 启动器在 PATH（或备好
   `GRASS_BRIDGE_BIN` 路径）；GRASS 版本记入部署记录。
2. 数据侧：准备专用的工作 gisdbase 副本，原始数据
   mapset 只读对待；桥指向的工作 mapset 应当是副本，
   不是唯一原件。
3. 环境变量配齐：`GRASS_BRIDGE_GISDBASE`（只写根目录，
   location/mapset 由调用时给名单独分量）、需要管控
   落点时设 `GRASS_BRIDGE_EXPORT_DIR`。
4. 首次启动后核对 token 文件
   `~/.grass-agent-bridge.token` 已生成且权限 0600；
   MCP 客户端配置按 examples/ 填写绝对路径。
5. 跑 `python3 live/selftest.py`（须 15/15 PASS）与
   `python3 scripts/probe_api.py`（有真实 GRASS 时须
   ready=true），两份输出留档。

## 验收清单（交付/迁移时逐项勾）

- [ ] selftest 全 PASS，输出原文在档
- [ ] probe_api.py JSON 在档（无 GRASS 时如实记
      grass_available=false）
- [ ] discover 回报：gisdbase 与 location 清单与磁盘
      一致、run_jobs 与代码枚举一致
- [ ] 负例抽查：缺 confirm 被拒、枚举外 job 被拒、非法
      图层名被拒，JSON 在档
- [ ] runs.jsonl 有对应条目且不含 token
- [ ] 覆盖抽查：用已有图层名做输出名，作业失败且原
      图层未被改动（或在校准记录中注明尚未实机验证）
- [ ] README「状态声明」的证据级别与本次实际验证范围
      一致（没上实机就不许写实机校准）

## 迁移注意

- 换机器只搬包目录与环境变量；token 文件不搬，到新机
  重新生成。
- 换 GRASS 大版本后，须按 docs/CALIBRATION.md 重新
  对账模板（g.list / r.info 输出形态与 --exec 行为是
  版本敏感点），再更新状态声明。
