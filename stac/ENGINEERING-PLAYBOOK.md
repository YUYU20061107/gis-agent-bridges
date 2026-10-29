# ENGINEERING-PLAYBOOK —— STAC 消费侧只读桥部署与验收手册（简版）

本包结构简单（stdio 服务端＋HTTP GET 客户端），手册只列
部署与验收的硬清单；原理与口径以 README / SKILL.md 为准。

## 部署清单

1. Python 3.x 可用；目标 STAC 目录可达（先用浏览器或 curl
   确认落地页能打开、是否需要 API Key）。
2. 环境变量配齐：`STAC_BASE_URL`（指到 STAC API 根，
   不带尾随 `/`）；目录需要 Key 时配 `STAC_API_KEY`，
   Key 永不入仓；需要管控落点时设
   `STAC_BRIDGE_OUTPUT_DIR`。
3. 首次启动后核对 token 文件 `~/.stac-agent-bridge.token`
   已生成且权限 0600；MCP 客户端配置按 examples/ 填写
   绝对路径。
4. 跑 `python3 live/selftest.py`（须 13/13 PASS）与
   `python3 scripts/probe_api.py`（有真实目录时须
   ready=true），两份输出留档。

## 验收清单（交付/迁移时逐项勾）

- [ ] selftest 全 PASS，输出原文在档
- [ ] probe_api.py JSON 在档（无目录时如实记 NOT_CONFIGURED）
- [ ] discover 回报：base_url 与预期一致、API Key 只显示
      是否配置、硬上限数值与代码一致
- [ ] 负例抽查：非法 bbox 被拒、limit 超限被拒、错 token
      被拒，JSON 在档
- [ ] calls.jsonl 有对应条目且不含 Key 与 token
- [ ] 导出抽查：GeoJSON 文件真实落盘、能被 JSON 解析、
      features 计数与工具回报一致，且明确不含影像本体
- [ ] README「状态声明」的证据级别与本次实际验证范围一致
      （没上实机就不许写实机校准）

## 迁移注意

- 换机器只搬包目录与环境变量；token 文件不搬，到新机
  重新生成。
- 换 STAC 目录或目录实现后，须按 docs/CALIBRATION.md
  重新对账检索（GET /search 支持与 eo 字段口径是实现
  敏感点），再更新状态声明。
