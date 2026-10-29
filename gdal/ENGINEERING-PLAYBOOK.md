# ENGINEERING-PLAYBOOK —— GDAL/OGR 工具桥部署与验收手册（简版）

本包结构简单（stdio 服务端＋GDAL 命令行子进程），手册
只列部署与验收的硬清单；原理与口径以 README / SKILL.md
为准。

## 部署清单

1. Python 3.x 可用；GDAL 四件套（gdalinfo / ogrinfo /
   gdal_translate / ogr2ogr）同版本，版本记入部署记录；
   不在 PATH 时备好四个 `GDAL_BRIDGE_*` 路径。
2. 首次启动后核对 token 文件
   `~/.gdal-agent-bridge.token` 已生成且权限 0600；MCP
   客户端配置按 examples/ 填写绝对路径。
3. 跑 `python3 live/selftest.py`（须 15/15 PASS）与
   `python3 scripts/probe_api.py`（有真实 GDAL 时须四件
   全 available），两份输出留档。
4. 向使用者交代两条本包特有口径：探查不产生 .aux.xml
   （PAM 强制关）；转换只写新文件、格式只有小枚举。

## 验收清单（交付/迁移时逐项勾）

- [ ] selftest 全 PASS，输出原文在档
- [ ] probe_api.py JSON 在档（无 GDAL 时如实记四件
      皆不可用）
- [ ] discover 回报：四件工具路径/版本一致、格式枚举
      与代码一致
- [ ] 负例抽查：缺 confirm 被拒、已存在输出被拒、远程
      路径被拒，JSON 在档
- [ ] runs.jsonl 有对应条目且不含 token
- [ ] 零副作用抽查（或在校准记录中注明尚未实机
      验证）：对某栅格跑一次 raster_stats 后，其目录
      无新增 .aux.xml
- [ ] README「状态声明」的证据级别与本次实际验证范围
      一致（没上实机就不许写实机校准）

## 迁移注意

- 换机器只搬包目录与环境变量；token 文件不搬，到新机
  重新生成。
- 换 GDAL 大版本后，须按 docs/CALIBRATION.md 重新
  对账模板（-json 键集与 ogrinfo 文本形态是版本敏感
  点），再更新状态声明。
