# 实机校准指南 —— pgRouting 消费侧只读桥 v0.1 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述要
达成的结果、验收标准与红线，具体做法由执行者决定；但每一步的原始
输出必须留档回传，没有 JSON 原文的回报视为未执行。

前置环境：一台装好 PostgreSQL + PostGIS + pgRouting 的机器，一份
已知内容的路网边表（如 osm2pgrouting 导入的小区域 ways），一个
**只读**数据库用户。校准机上先跑通 `live/selftest.py`（协议自检
12/12）再进入实机步骤——自检不过，先修协议层，不许往下走。

## 零基础试用路径（烟雾测试，不替代正式校准）

没有现成数据库时，先用包内样本把“数据库能起、探针能通、模板能
返回”走通；它不满足下面正式校准对只读用户、负例与 directed 两
种取值的全部要求：

1. 在 `pgrouting/examples/` 执行 `docker compose up -d`，等服务
   健康后回到 `pgrouting/`。该 Compose 只把样本库绑在
   `127.0.0.1:54329`，首次初始化会执行 `sample-network.sql`。
   样本卷若已初始化过，按 README 的说明删除**仅样本项目**的卷后
   再重建。
2. 设置 `PGHOST=127.0.0.1`、`PGPORT=54329`、
   `PGDATABASE=pgrouting_sample`、`PGUSER=pgrouting`、
   `PGPASSWORD=pgrouting_local_only`（只限这个本地样本库）与
   `PGROUTING_ALLOWED_TABLES=sample_ways`，跑
   `python3 scripts/probe_api.py`；预期 `ready=true`，
   `summary_probe` 命中 `sample_ways` 且为 5 个节点、6 条边。
3. 若由 MCP 客户端拉起服务端，把非密码连接变量复制到客户端的
   `env` 段；密码用 `~/.pgpass` 或客户端的安全环境变量入口提供，
   不写入示例配置。不要假设 GUI 客户端继承终端的 `export`。
4. 按 README/LIVE 的 token 规则取得 `_token`（服务端 env 优先，
   否则读 `~/.pgrouting-agent-bridge.token`），每次 tools/call
   都显式附带它。先调 summary，再调 route 1 -> 3
   （directed=true），预期值见下一步的独立参照。
5. 预期参照在运行桥之前已写在 `sample-network.sql` 里并可按图
   手算：summary 为 5/6；1 -> 3 的节点序列 `[1, 4, 5, 3]`、
   边序列 `[3, 4, 5]`、total_cost=3；导出应有 3 个 features。
   再试 1 -> 5 时，预期节点 `[1, 4, 5]`、边 `[3, 4]`、
   total_cost=2。

样本路径走到这里只算烟雾测试通过。若要把 `sample_ways` 用作正式
校准数据，执行者必须先逐行阅读 SQL、独立复算上面的图与代价，并
换用只读数据库用户后从下面「目标结果」第 1 项重新走完整工单；
不得因为烟雾测试返回一致就跳过负例或把样本预期改成桥的输出。

## 目标结果（全部达成才算完成）

1. probe_api.py 在目标库全绿：PostGIS / pgRouting 版本落档，
   SELECT 1 与允许表 summary 试算通过（ready=true）。
2. 路径模板对账通过：一条已知路径的节点序列与 total_cost 与
   独立参照（手算小图或 QGIS 里量算）一致。
3. GeoJSON 导出对账通过：导出文件能在 QGIS 打开，几何走向与路径
   一致，features 数 = 路径边数。
4. 负例口径成立：无路径返回 found=false（不是报错、更不是假路径）；
   只读用户下五工具全通；缺 geom 的表做导出时如实 PSQL_FAILED。
5. 校准结论回写 README「状态声明」：环境与版本、逐项结果、与模板
   的差异点；selftest 保持全 PASS。

## 校准顺序（不要跳步）

1. **连通与版本**：配好 PG* 环境变量与 PGROUTING_ALLOWED_TABLES，
   跑 probe_api.py 并完整回传 JSON。ready 不为 true 就停在这里，
   先解决连接/扩展，不许往下走。
2. **summary 对账**：对样本边表跑 network_summary，把 node_count 与
   `SELECT count(DISTINCT ...)` 的独立查询、edge_count 与表行数
   逐项核对（用你自己的客户端查，参照值不许经桥产生）。若用包内
   `sample_ways`，在看桥输出前先按 SQL 中的图独立复算为 5 个节点、
   6 条边；不得直接抄桥返回值当参照。
3. **路径对账**：选一条参照明确的起终点跑 route_dijkstra：节点
   序列、每条 edge 的 cost、total_cost 与参照逐项对；有向/无向
   （directed=false）各跑一次，确认 directed 参数真实生效。若用
   包内样本，正式对账前先独立手算：directed=true 的 1 -> 3 应经
   `[3, 4, 5]` 三条边、节点 `[1, 4, 5, 3]`、total_cost=3。
4. **导出对账**：同一条路径跑 export_route_geojson，在 QGIS 里
   加载：图层能渲染、走向与路径一致、features 计数与 route 的
   边数（rows 中 edge != -1 的行数）一致。
5. **负例验证**：无路径起终点、不存在的节点 id、缺 geom 的表导出、
   允许集合外的表名，四种情况逐项确认报错/口径如实（found=false /
   PSQL_FAILED / TABLE_NOT_ALLOWED），并回传原始 JSON。
6. **收紧与回归**：若目标 pgRouting 版本下模板有差异（返回列名、
   json 聚合为空集的行为等），先记录差异原文，再改模板或文档；
   跑 selftest；把改动点逐条列清回传。

## 红线

- 校准全程只许只读查询；不许为了让模板跑通去改样本表结构、加列
  或灌数据。样本须在桥调用之外准备并说明来源；使用包内
  `sample_ways` 时，必须先逐行核对 SQL 并独立手算参照，不能在
  看到桥输出后回改样本或预期凑绿。
- 密码只经环境变量或 ~/.pgpass，不许出现在任何回传、日志或文件里。
- 对账参照值必须来自桥之外的独立来源；拿桥自己的输出对账等于
  没校准。
- 任一步对不上：停在该步、回传差异，不许改判定口径凑绿。
