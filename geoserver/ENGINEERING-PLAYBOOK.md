# ENGINEERING-PLAYBOOK —— GeoServer 消费侧只读桥部署与验收手册（简版）

本包结构简单（stdio 服务端＋HTTP GET 客户端），手册只列
部署与验收的硬清单；原理与口径以 README / SKILL.md 为准。

## 部署清单

1. Python 3.x 可用；目标 GeoServer 可达（先用浏览器或 curl
   确认 `/rest/about/version.json` 的认证要求）。
2. 环境变量配齐：`GEOSERVER_BASE_URL`（指到 GeoServer 的
   web 应用根，不带尾随 `/`）；REST 目录需要认证时配
   `GEOSERVER_USER` / `GEOSERVER_PASSWORD`，密码永不入仓。
3. 首次启动后核对 token 文件
   `~/.geoserver-agent-bridge.token` 已生成且权限 0600；
   MCP 客户端配置按 examples/ 填写绝对路径。
4. 跑 `python3 live/selftest.py`（须 12/12 PASS）与
   `python3 scripts/probe_api.py`（有真实实例时须
   ready=true），两份输出留档。

## 验收清单（交付/迁移时逐项勾）

- [ ] selftest 全 PASS，输出原文在档
- [ ] probe_api.py JSON 在档（无实例时如实记 NOT_CONFIGURED）
- [ ] discover 回报：base_url 与预期一致、认证只显示是否
      配置、硬上限数值与代码一致
- [ ] 负例抽查：非法图层名被拒、错 token 被拒，JSON 在档
- [ ] calls.jsonl 有对应条目且不含密码与 token
- [ ] 目录抽查：桥的图层清单与原始 REST JSON 计数一致
      （或在校准记录中注明尚未实机对账）
- [ ] README「状态声明」的证据级别与本次实际验证范围一致
      （没上实机就不许写实机校准）

## 迁移注意

- 换机器只搬包目录与环境变量；token 文件不搬，到新机
  重新生成。
- 换 GeoServer 大版本后，须按 docs/CALIBRATION.md 重新
  对账（REST JSON 字段与 GetCapabilities 命名空间是版本
  敏感点），再更新状态声明。
