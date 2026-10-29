# gnss-validation — GNSS×GIS 离线轨迹验证桥

> **EN summary:** An offline GNSS track validation bridge (MCP, stdio, pure Python stdlib). It parses NMEA/GPX logs from a local work directory, measures per-point deviation against a local GeoJSON reference layer (roads/areas), flags jumps/teleports/stationary drift, reports fix/HDOP-stratified deviation statistics, and writes corrected tracks (snap / smooth / control-point offset) as new GeoJSON files only — never overwriting originals. Write tools require an explicit `confirm=true`; every call requires a local token. Status: protocol-selftest level (22/22 checks on synthetic data with hand-computed expectations); **not yet calibrated against real-world tracks** — see `docs/CALIBRATION.md`. Real-time streams (serial/NTRIP) are planned for v0.2 and are **not** implemented.

## 这是什么

把「GNSS 轨迹到底准不准」从感觉变成可复算的数字：轨迹日志（NMEA/GPX）逐点对本地 GIS 参考图层（道路线、区域面）量最短距离，给出偏离分布、超限点清单、跳点/漂移清单，并按 fix 类型与 HDOP 分层统计；需要纠偏时产出**新** GeoJSON（吸附/平滑/控制点偏移），原件永远不动，每点保留原始坐标与修正量，结论可独立复算。

v0 是**离线轨迹验证版**：全部输入是本地文件，不连任何设备、不联网。实时串口/NTRIP 流列在 v0.2，未做（见 `live/LIVE.md` 与 `ROADMAP.md`）。

## 状态（如实标注）

- 完成度：**协议自检级**——`live/selftest.py` 22/22 通过，自检数据为合成轨迹，期望值（20.015 m 偏离、段速 113.1/93.1 m/s、GPS 组 RMS 7.076 m 等）全部独立手算，不取桥自身产出当期望。
- **未实机校准**：还没有用真实手机 GNSS 轨迹＋真实参考图层（如 OSM 路网）对过账。校准工单见 `docs/CALIBRATION.md`，完成前不要把本桥的数字当成真实世界精度结论。

## 工具（8 个）

| 工具 | 干什么 | 写文件 |
|---|---|---|
| `gnss_status` | NMEA 日志汇总：点数、fix 分布、卫星数、HDOP 范围、时间跨度、解析计数 | 否 |
| `gnss_track_read` | 读 NMEA/GPX 轨迹为结构化点列；返回点数硬上限 10000，超限截断并明示 | 否 |
| `gnss_validate_against_layer` | 逐点到参考图层最短距离、偏离分布、超限点清单（阈值默认 10 m，含最近点坐标可复算） | 否 |
| `gnss_detect_jumps` | 跳点/瞬移/静止漂移检测（速度、加速度、漂移阈值可参数化） | 否 |
| `gnss_accuracy_report` | 按 fix/HDOP 分层的偏离统计；无参考层时退化为自洽统计并**明示不是精度真值** | 否 |
| `gnss_correct_snap` | 逐点吸附到参考图层最近点 | 是（confirm 闸） |
| `gnss_correct_smooth` | 居中滑动平均平滑（窗口可参数化，须 ≥3 奇数） | 是（confirm 闸） |
| `gnss_correct_offset` | 控制点配对算平均偏移整轨平移；**只给 1 个配对时只报偏移、不产文件** | 是（confirm 闸，≥2 配对才纠偏） |

## 安全口径（与全系一致）

- 纯 Python 标准库、stdio 传输、只在本机跑；无任意代码执行工具。
- token 闸：每次 `tools/call` 必须带 `_token`（环境变量 `GNSS_BRIDGE_TOKEN` 或 `~/.gnss-validation-bridge.token`），否则 `BAD_TOKEN`。
- 路径防穿越：一切文件参数只接受 `GNSS_WORK_DIR` 内的相对路径，解析后越界（`../`、绝对路径、符号链接逃逸）一律拒绝。
- 写操作 confirm 闸＋只产新文件：输出必须是不存在的 `.geojson`，永不覆盖原件；输入文件大小上限 64 MiB、返回点数上限 10000。

## 距离口径（先说清，免得误读数字）

点到图层距离用**等距圆柱平面近似**（以图层平均纬度定经度尺度），公里级以内适用，不是测地线精确距离；每个工具的返回里都带 `distance_method` 字段重申这一口径，每点距离可由原始坐标按同一公式独立复算。无参考层时的「自洽统计」量的是抖动量级，系统性偏移它看不见——桥会在返回里直说，不许把自洽写成精度真值。

## 快速上手

```bash
export GNSS_WORK_DIR=/path/to/your/track-workdir   # 把 .nmea/.gpx 与参考 .geojson 放这里
python3 scripts/probe_api.py        # 离线探针：环境＋内置样本链路
python3 live/selftest.py            # 一键自检（22 项，合成数据）
python3 live/mcp_server.py          # 启动 MCP 服务端（stdio）
```

MCP 客户端配置见 `examples/mcp-client-config.json`；示例数据在 `examples/`（`sample-track.nmea` 一条含已知 20 m 偏离点与已知跳点的合成轨迹、`sample-road.geojson` 一条直线参考道路）；示例提示词见 `examples/prompts.md`。

## 文件

| 路径 | 内容 |
|---|---|
| `scripts/gnss_bridge.py` | 解析/量距/检测/纠偏的纯标准库实现 |
| `scripts/probe_api.py` | 离线探针（单行 JSON 结果，ready 布尔） |
| `live/mcp_server.py` | MCP 服务端（stdio＋token 闸＋记账） |
| `live/selftest.py` | 一键自检（期望值独立手算） |
| `live/LIVE.md` | 接入说明与故障排查 |
| `docs/CALIBRATION.md` | 校准状态与校准工单（未校准） |
| `SKILL.md` | 给 Agent 的使用规矩 |
| `ROADMAP.md` / `ENGINEERING-PLAYBOOK.md` | 路线与工程手册 |
