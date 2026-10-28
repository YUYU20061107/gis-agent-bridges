# ENGINEERING-PLAYBOOK —— istSOS 消费侧只读桥部署与验收手册（简版）

本包结构简单（stdio 服务端＋urllib 只读客户端），手册只列部署与
验收的硬清单；原理与口径以 README / SKILL.md 为准，校准流程以
docs/CALIBRATION.md 为准。**本手册的验收通过 ≠ istSOS4 已校准**：
截至本版，本包只过了协议级自检，istSOS4 本体未实测。

## 架构一页

- `live/mcp_server.py`：stdio MCP 服务端（纯标准库），不监听端口；
  对 STA 服务端的唯一网络出口是内部 `_sta_get`，只发 GET。
- `live/selftest.py`：协议级自检，自带跑在 127.0.0.1 随机端口的
  假 STA 服务端回放固定 JSON，不出外网、不需要真实服务。
- `scripts/probe_api.py`：独立只读连通探针（不经 MCP），把目标
  服务端的根/Things/Datastreams 探查结果输出成一行 JSON 留档。
- 本地落盘只有两处：导出 GeoJSON（文件名由桥生成）、调用记录
  `~/.istsos-agent-bridge/calls.jsonl`（仅工具名与成败）。

## 安全边界（部署时逐项确认）

1. 远端全只读：没有任何写工具；发现自己在拼 POST/PUT/DELETE
   即为越界，立即停。
2. 基地址只从 `ISTSOS_BASE_URL` 读，代码无默认端点；地址指向
   哪个服务端，信任边界就到哪——公开演示端点只配做首次连通
   验证，数据内容不可信、不作结论依据。
3. token 守卫：`ISTSOS_BRIDGE_TOKEN`（env）优先于 token 文件
   （默认 `~/.istsos-agent-bridge.token`）；两者皆无时启动生成
   随机 token 写入文件。注意：本包当前**未对 token 文件强制
   0600 权限**，部署时自行核对该文件及其目录的访问权限。
4. 防拉爆硬上限是代码常量（$top≤100、nextLink≤3 页/总量≤300、
   观测≤100、导出≤500、单响应≤2MiB、超时 10s），超限以
   LIMIT_EXCEEDED 拒绝；不许为一次拉取改常量放行。
5. 导出几何是所属 Thing 的第一个 Location（全流共用点位），
   引用结果时必须带这个口径；无位置回 NO_LOCATION，不补坐标。

## 部署清单

1. Python 3.x 可用（纯标准库，无第三方依赖）；仓库文件齐：
   live/、scripts/、examples/、docs/ 都在。
2. 跑离线自检：`python3 live/selftest.py` 须 12/12 PASS，输出留档。
3. 选定目标 STA 服务端并探针留档：先按 README「快速开始」用
   `scripts/probe_api.py` 探一次（公开演示端点或自建服务均可），
   JSON 输出存档；探针未 ready 不许进下一步。
4. 环境变量配齐：`ISTSOS_BASE_URL`（必填、末尾不带 /）、
   `ISTSOS_BRIDGE_TOKEN` 或 token 文件二选一、
   `ISTSOS_BRIDGE_OUTPUT_DIR`（需要管控导出落点时设）。
5. MCP 客户端配置按 examples/ 填写绝对路径；`command` 用
   `python`，本机只有 `python3` 时改 `python3`。
6. 首次 tools/call 带 `_token` 做 istsos_discover＋istsos_ping，
   回报与预期一致（基地址、硬上限、token 守卫开启）再放行
   业务工具。

## 验收清单（交付/迁移时逐项勾）

- [ ] selftest 12/12 PASS，输出原文在档
- [ ] probe_api.py JSON 在档（目标服务端 root.ok=true、
      Things/Datastreams 计数有值或失败原因明确）
- [ ] discover 回报：base_url 与目标一致、limits 与代码常量
      一致、token_guard=true
- [ ] 负例抽查：无/错 token 被 BAD_TOKEN 拒、limit 超限被
      LIMIT_EXCEEDED 拒，JSON 在档
- [ ] 导出抽查：GeoJSON 真实落盘、能被 JSON 解析、features
      计数与工具回报一致，且文件内 geometry_note 在位
- [ ] calls.jsonl 有对应条目且不含观测数据与 token
- [ ] README「校准状态」的证据级别与本次实际验证范围一致
      （只探通公开演示端点就只记 STA 协议级，不许写
      istSOS4 已验证）

## 迁移注意

- 换机器只搬包目录与环境变量；token 文件不搬，到新机重新生成，
  并同步更新客户端侧保存的 token。
- 换 STA 服务端或服务端大版本后，先重跑 probe_api.py，再按
  docs/CALIBRATION.md 重新对账（分页、计数与时间格式行为是
  实现敏感点），最后才更新状态声明。
