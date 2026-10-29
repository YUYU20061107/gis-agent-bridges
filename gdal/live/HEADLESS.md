# HEADLESS —— GDAL/OGR 工具桥运行说明

## 形态

`live/mcp_server.py` 是纯 Python 标准库的 **stdio MCP
服务端**：它没有应用内桥，不监听任何 TCP 端口，也不常驻
任何 GDAL 进程。

- MCP 客户端按需拉起服务端进程，双方只通过 stdin/stdout
  传 MCP JSON-RPC；stdout 是协议通道，运行日志只写 stderr。
- 业务工具按需以参数数组启动 GDAL 命令行工具子进程
  （gdalinfo / ogrinfo / gdal_translate / ogr2ogr），模板
  写死在 `../scripts/gdal_bridge.py`，跑完即退。
- 所有子进程的环境都被强制设 `GDAL_PAM_ENABLED=NO`：
  只读探查（如 gdalinfo -stats）不会在原件旁边写下
  `.aux.xml` 伴生文件。
- 本机没有 GDAL 时，探查/转换工具如实返回
  `NOT_AVAILABLE`；ping/discover 照常回报可用性。

首次使用前先看 `../README.md` 的定位与状态声明；接真实
GDAL 后，校准顺序与验收口径以 `../docs/CALIBRATION.md`
为准。手动直接运行服务端时，它会静默等待 stdin 输入，这
不是卡死——它在等 MCP 客户端发 JSON-RPC 消息。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---:|---|
| `GDAL_BRIDGE_TOKEN` | 否 | 若设置，服务端以它为期望 token，优先于 token 文件 |
| `GDAL_BRIDGE_GDALINFO` | 否 | gdalinfo 不在 PATH 时指定其完整路径（自检也经此注入替身） |
| `GDAL_BRIDGE_OGRINFO` | 否 | 同上，ogrinfo |
| `GDAL_BRIDGE_GDAL_TRANSLATE` | 否 | 同上，gdal_translate |
| `GDAL_BRIDGE_OGR2OGR` | 否 | 同上，ogr2ogr |
| `GDAL_BRIDGE_TIMEOUT` | 否 | 单次工具调用超时秒数（默认 60） |

注意进程归属：在终端里 `export` 的变量只对从该终端启动的
服务端与探针有效。若 Claude Desktop 等 GUI 客户端负责拉起
服务端，必须把同一组变量写进该客户端的 MCP 配置 `env`
段，不能指望它继承另一个终端的 `export`。尤其注意：本包
**不提供** `GDAL_PAM_ENABLED` 的放行开关——桥对子进程
强制为 NO，调用方在自己环境里设成 YES 也会被覆盖，这是
刻意设计，不是故障。

## token 机制（调用方必须显式附带）

本包的 token 守卫常开：**服务端不会替调用方自动附带
`_token`**。`initialize`、`tools/list` 与协议 `ping` 不查
token；每一次 `tools/call`（包括本包的 `gdal_ping` 与
`gdal_discover`）都必须在 `arguments` 里亲自带上
`_token`，且与服务端期望值完全一致，否则返回 `BAD_TOKEN`。

服务端按以下顺序确定期望 token：

1. 若服务端进程环境里有非空的 `GDAL_BRIDGE_TOKEN`，使用
   该值，不再看 token 文件；
2. 否则读取 token 文件：
   - Linux/macOS：`~/.gdal-agent-bridge.token`
   - Windows：`%USERPROFILE%\.gdal-agent-bridge.token`
3. 若环境变量未设、token 文件也不存在，服务端**启动时**
   生成一个随机 token，写入上述文件并尽量设为 0600，同时
   在 stderr 打印文件路径。

不要把真实 token 写进仓库、客户端配置示例、提示词、回报或
截图；也不要靠反复猜测重试 `BAD_TOKEN`。

### 完整 tools/call 示例（含 confirm 的写类调用）

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "gdal_convert_raster",
    "arguments": {
      "_token": "<TOKEN_FROM_ENV_OR_TOKEN_FILE>",
      "path": "/data/dem.tif",
      "output": "/data/dem_copy.tif",
      "format": "GTiff",
      "confirm": true
    }
  }
}
```

`confirm` 只能在用户明确同意后填 true；Agent 不许自作主张
补上。缺 confirm 的转换调用一律 `CONFIRM_REQUIRED`，且在
启动 GDAL 之前就拒绝。

## 启动与注册

手动启动（通常只用于确认进程能起来，实际使用由 MCP 客户端拉起）：

```bash
python3 live/mcp_server.py
```

客户端注册示例见 `../examples/mcp-client-config.json`；占位符
与跨平台 `command` 的替换方式集中写在 `../examples/prompts.md`。

转换类调用日志在 `~/.gdal-agent-bridge/runs.jsonl`，只记
工具名、输入输出路径、状态与耗时，不记 token。

## 自检

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 15/15 PASS
```

自检用四个假二进制替身验证协议、解析与安全闸（包括断言
子进程实际拿到的 GDAL_PAM_ENABLED 为 NO），不调用真实
GDAL。自检通过仍只是协议自检级证据，不是实机校准。

## 故障排查

| 现象 | 先查什么 |
|---|---|
| `BAD_TOKEN` | 是否**每一次** tools/call 都带了 `_token`；值是否与服务端进程实际使用的来源一致。只要服务端 env 里设置了 `GDAL_BRIDGE_TOKEN`，它就覆盖 token 文件；改 env 或 token 后要重启服务端。 |
| 客户端列不出工具 | 先单独跑 `live/selftest.py`；再核对客户端配置中的 Python 命令与 `mcp_server.py` 绝对路径。手动启动后无输出是正常等待状态。 |
| `NOT_AVAILABLE` | 在**拉起服务端的同一环境**里确认四件工具可用，或用 `GDAL_BRIDGE_*` 变量逐件指定完整路径。GUI 客户端的 PATH 与终端可能不同。 |
| `REMOTE_PATH_REJECTED` | 输入是 http(s) 或 /vsi 路径：本桥只探查本地文件。先把文件下到本地再探查，不要试图绕过。 |
| `PATH_NOT_FOUND` | 输入路径不存在或不是文件：核对路径逐字无误（桥在调用二进制前就拒绝，不会产生 GDAL 报错）。 |
| `PARSE_FAILED` | 多为老版本 GDAL 不支持 `gdalinfo -json`：回报里带了原文开头，先升级 GDAL 或记录版本差异，不要改口径硬凑。 |
| `CONFIRM_REQUIRED` | 转换调用缺 `confirm=true`：先向用户说明输入、输出与格式，得到明确同意后再带上，不许自行补。 |
| `OUTPUT_EXISTS` / `OUTPUT_EXT_MISMATCH` | 输出已存在（不覆盖）或扩展名与格式不匹配：换新文件名/改对扩展名后重试。 |
| 改了配置却像没生效 | MCP 客户端通常缓存已拉起的服务端进程；修改 env、token 或二进制路径后，重启服务端或重启客户端再试。 |
