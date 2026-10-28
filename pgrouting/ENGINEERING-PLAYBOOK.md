# ENGINEERING-PLAYBOOK —— pgRouting 消费侧只读桥部署与验收手册（简版）

本包结构简单（stdio 服务端＋psql 子进程），手册只列部署与验收的
硬清单；原理与口径以 README / SKILL.md 为准。

## 部署清单

1. Python 3.x 可用，`psql` 在 PATH（或备好 `PGROUTING_PSQL` 路径）。
2. 数据库侧：为桥单独建**只读用户**，只授目标边表的 SELECT 权限；
   密码经 `PGPASSWORD` 环境变量或 `~/.pgpass` 提供，永不入仓。
3. 环境变量配齐：PGHOST/PGPORT/PGDATABASE/PGUSER、
   `PGROUTING_ALLOWED_TABLES`（只列真的要查的表，不许图省事放宽）、
   需要管控落点时设 `PGROUTING_EXPORT_DIR`。
4. 首次启动后核对 token 文件 `~/.pgrouting-agent-bridge.token`
   已生成且权限 0600；MCP 客户端配置按 examples/ 填写绝对路径。
5. 跑 `python3 live/selftest.py`（须 12/12 PASS）与
   `python3 scripts/probe_api.py`（有真实库时须 ready=true），
   两份输出留档。

## 验收清单（交付/迁移时逐项勾）

- [ ] selftest 全 PASS，输出原文在档
- [ ] probe_api.py JSON 在档（无真实库时如实记 psql_available=false）
- [ ] discover 回报：allowed_tables 与预期一致、PGPASSWORD 只显示
      是否设置、探针 SELECT 1 结果与环境相符
- [ ] 负例抽查：允许集合外的表名被拒、非法文件名被拒，JSON 在档
- [ ] runs.jsonl 有对应条目且不含密码与 token
- [ ] 导出抽查：GeoJSON 文件真实落盘、能被 JSON 解析、features
      计数与工具回报一致
- [ ] README「状态声明」的证据级别与本次实际验证范围一致
      （没上实机就不许写实机校准）

## 迁移注意

- 换机器只搬包目录与环境变量；token 文件不搬，到新机重新生成。
- 换 pgRouting 大版本后，须按 docs/CALIBRATION.md 重新对账模板
  （返回列与 json 聚合行为是版本敏感点），再更新状态声明。
