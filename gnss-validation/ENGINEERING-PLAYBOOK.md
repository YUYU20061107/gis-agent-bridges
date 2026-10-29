# ENGINEERING-PLAYBOOK — gnss-validation

本包的工程规矩。改代码前先读；与全仓 `docs/` 的通则冲突时以更严的一侧为准。

## 分层

- `scripts/gnss_bridge.py`：纯函数库（解析、量距、检测、纠偏、路径守卫），不感知 MCP；所有错误走 `BridgeError(error_code, message)`。
- `live/mcp_server.py`：只做协议、token、记账与参数校验，业务一律调库函数；新工具先在库里实现并单测，再挂到服务端。
- `scripts/probe_api.py` / `live/selftest.py`：验证面。改库函数的行为，同步改这两处的期望值——**期望值必须独立手算**，禁止把桥的输出抄进期望。

## 不变量（改动不得破坏）

- 路径只进不出：输入/输出都经 `resolve_in_path` / `resolve_out_path`（realpath 后 commonpath 校验），输出只许新 `.geojson`、`open(...,"x")` 独占创建＋写前二次确认不存在。
- 写工具三件套：描述以「」开头、schema 带 `confirm` 属性、处理函数第一行 `_require_confirm`——全仓 `check_invariants.py` 机器查这三样。
- 硬上限集中在库头常量：`MAX_TRACK_POINTS=10000`、`MAX_FILE_BYTES=64MiB`、`MAX_OVER_LIST=200`；改常量须同步 README、SKILL 与自检。
- 距离口径只有一个实现：`distance_to_layer`＋`LocalPlane`（等距圆柱近似）；任何新统计都复用它，不许另写一套测地线公式造成双口径。口径声明 `DIST_METHOD_NOTE` 必须出现在每个涉距工具的返回里。
- 自洽≠真值：无图层的统计路径里 `basis` 必须是 `self-consistency` 且 note 含「不是精度真值」。

## 解析口径备忘

- NMEA：校验和不过整句跳过并计数；GGA 为主点源，日期预扫首条 RMC 定初始值、主解析按最近 RMC 滚动（跨日轨迹靠这个）；无 RMC 的文件点没有时间轴，时间相关检测跳过并在 notes 里说明——不要给无日期文件编造日期。
- GPX：只认 trkpt；fix/sat/hdop 子元素缺失即 None，不许猜。
- 坐标出入参一律 (lat, lon) 度；GeoJSON 坐标序是 [lon, lat]，`track_feature_collection` 是唯一的转换点。

## 发版前检查

1. `python3 live/selftest.py` 全过（改动后条数只增不减）。
2. `python3 scripts/probe_api.py` 输出 `ready: true`。
3. 仓根 `manifest/build_manifest.py` 重生成后本包条目无 error；`check_invariants.py`、`check_readme_counts.py` 全过。
4. 脱敏自查：包内不得出现真实轨迹、本机绝对路径、任何 token 值。
