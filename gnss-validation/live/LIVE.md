# LIVE — gnss-validation 接入说明

## 形态

stdio MCP 服务端，纯 Python 标准库，无第三方依赖，不需要 GNSS 设备、不联网。全部输入输出都是 `GNSS_WORK_DIR` 内的本地文件。

**实时流未做（如实声明）**：串口 NMEA 实时读取、NTRIP 差分流是 v0.2 的计划项，v0 没有任何实时工具；不要按实时桥的方式向用户介绍它。

## 启动

```bash
export GNSS_WORK_DIR=/path/to/track-workdir   # 轨迹与参考图层放这个目录
python3 live/mcp_server.py
```

客户端配置样例见 `examples/mcp-client-config.json`。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `GNSS_WORK_DIR` | 是 | 工作目录：轨迹（.nmea/.log/.txt/.gpx）、参考图层（.geojson）与纠偏输出都只在这个目录内，用相对路径引用 |
| `GNSS_BRIDGE_TOKEN` | 否 | 调用 token；不设则读 `~/.gnss-validation-bridge.token`，文件也没有时启动自动生成（0600，打印到 stderr 一次） |

## token 机制

每次 `tools/call` 的参数里带 `_token` 且与服务端 token 全等才执行，否则返回 `BAD_TOKEN`。记账文件 `~/.gnss-validation-bridge/runs.jsonl` 每次调用追加一行（工具名、输入文件名、状态、耗时；不含 token、不含坐标）。

## 自检与探针

```bash
python3 live/selftest.py     # 22 项：正例＋路径穿越/超限/单配对/未 confirm 等负例
python3 scripts/probe_api.py # 环境与内置样本链路探针，输出单行 JSON（ready 字段）
```

自检把 HOME 与 GNSS_WORK_DIR 指到临时目录，不污染包目录与用户目录。

## 故障排查

| 现象 | 多半原因 | 处理 |
|---|---|---|
| `NOT_CONFIGURED` | 没设 `GNSS_WORK_DIR` | 设置后重启服务端 |
| `WORK_DIR_MISSING` | 目录不存在 | 先建目录并把文件放进去 |
| `PATH_OUTSIDE_WORKDIR` | 用了绝对路径或 `../` | 改用工作目录内相对路径 |
| `BAD_TOKEN` | 客户端没带/带错 `_token` | 对齐环境变量或 token 文件内容后重试 |
| `CONFIRM_REQUIRED` | 写工具没传 `confirm=true` | 经用户确认后再传 |
| `OUTPUT_EXISTS` | 输出名撞已有文件 | 换新文件名（桥永不覆盖） |
| `NO_POINTS` | 文件里没有有效定位点 | 看 gnss_status 的 parse_info：坏校验和/无定位行计数会说明原因；GGA-only 且无 RMC 的文件没有日期，速度/漂移检测会跳过（轨迹点仍可读） |
| validate 数字偏大 | 参考图层不全或坐标系不是 WGS84 经纬度 | 确认图层坐标为经纬度且覆盖轨迹范围 |
