# HEADLESS —— GRASS GIS 无头桥运行说明

## 形态

`live/mcp_server.py` 是纯 Python 标准库的 **stdio MCP
服务端**：它没有应用内桥，不监听任何 TCP 端口。GRASS GIS
没有官方支持的“附着到已打开 GUI 会话”的通道，本包只有
无头批处理形态：

- MCP 客户端按需拉起服务端进程，双方只通过 stdin/stdout
  传 MCP JSON-RPC；stdout 是协议通道，运行日志只写 stderr。
- 业务工具按需以参数数组启动 `grass <mapset> --exec <模块>`
  子进程，模块与参数名都是写死的模板（见
  `../scripts/grass_bridge.py`），跑完即退，不常驻 GRASS
  会话。
- 没有 GRASS 的机器上，依赖 GRASS 的工具如实返回
  `GRASS_NOT_AVAILABLE`；`grass_location_info` 只读
  location 文件，不启动 GRASS，无 GRASS 时也能用。

首次使用前先看 `../README.md` 的定位与状态声明；接真实
GRASS 后，校准顺序与验收口径以 `../docs/CALIBRATION.md`
为准。手动直接运行服务端时，它会静默等待 stdin 输入，这
不是卡死——它在等 MCP 客户端发 JSON-RPC 消息。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---:|---|
| `GRASS_BRIDGE_GISDBASE` | 业务工具必填 | GRASS 数据库根目录；location/mapset 只能是其下的单个目录名，工具参数里不接受路径 |
| `GRASS_BRIDGE_TOKEN` | 否 | 若设置，服务端以它为期望 token，优先于 token 文件 |
| `GRASS_BRIDGE_BIN` | 否 | grass 不在 PATH 时指定其完整路径 |
| `GRASS_BRIDGE_EXPORT_DIR` | 否 | 设置后导出文件只能落在此目录内 |
| `GRASS_BRIDGE_TIMEOUT` | 否 | 单次 grass 调用超时秒数（默认 120） |

注意进程归属：在终端里 `export` 的变量只对从该终端启动的
服务端与探针有效。若 Claude Desktop 等 GUI 客户端负责拉起
服务端，必须把同一组变量写进该客户端的 MCP 配置 `env`
段，不能指望它继承另一个终端的 `export`。

## token 机制（调用方必须显式附带）

本包的 token 守卫常开：**服务端不会替调用方自动附带
`_token`**。`initialize`、`tools/list` 与协议 `ping` 不查
token；每一次 `tools/call`（包括本包的 `grass_ping` 与
`grass_discover`）都必须在 `arguments` 里亲自带上
`_token`，且与服务端期望值完全一致，否则返回 `BAD_TOKEN`。

服务端按以下顺序确定期望 token：

1. 若服务端进程环境里有非空的 `GRASS_BRIDGE_TOKEN`，使用
   该值，不再看 token 文件；
2. 否则读取 token 文件：
   - Linux/macOS：`~/.grass-agent-bridge.token`
   - Windows：`%USERPROFILE%\.grass-agent-bridge.token`
3. 若环境变量未设、token 文件也不存在，服务端**启动时**
   生成一个随机 token，写入上述文件并尽量设为 0600，同时
   在 stderr 打印文件路径。

不要把真实 token 写进仓库、客户端配置示例、提示词、回报或
截图；也不要靠反复猜测重试 `BAD_TOKEN`。

### 完整 tools/call 示例（含 confirm 的执行类调用）

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "grass_run_module",
    "arguments": {
      "_token": "<TOKEN_FROM_ENV_OR_TOKEN_FILE>",
      "location": "demo",
      "mapset": "user1",
      "job": "slope_aspect",
      "params": {"elevation": "elevation", "slope": "slope1",
                 "aspect": "aspect1"},
      "confirm": true
    }
  }
}
```

`confirm` 只能在用户明确同意后填 true；Agent 不许自作主张
补上。缺 confirm 的执行/写类调用一律 `CONFIRM_REQUIRED`，
且在启动 GRASS 之前就拒绝。

## 启动与注册

手动启动（通常只用于确认进程能起来，实际使用由 MCP 客户端拉起）：

```bash
python3 live/mcp_server.py
```

客户端注册示例见 `../examples/mcp-client-config.json`；占位符
与跨平台 `command` 的替换方式集中写在 `../examples/prompts.md`。

写/执行类调用日志在 `~/.grass-agent-bridge/runs.jsonl`，
只记工具名、作业、状态与耗时，不记 token。

## 自检

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 15/15 PASS
```

自检用假 grass 替身与纯文件搭的假 location 验证协议、工具面
与安全闸，不启动真实 GRASS。自检通过仍只是协议自检级证据，
不是实机校准。

## 故障排查

| 现象 | 先查什么 |
|---|---|
| `BAD_TOKEN` | 是否**每一次** tools/call 都带了 `_token`；值是否与服务端进程实际使用的来源一致。只要服务端 env 里设置了 `GRASS_BRIDGE_TOKEN`，它就覆盖 token 文件；改 env 或 token 后要重启服务端。 |
| 客户端列不出工具 | 先单独跑 `live/selftest.py`；再核对客户端配置中的 Python 命令与 `mcp_server.py` 绝对路径。手动启动后无输出是正常等待状态。 |
| `GRASS_NOT_AVAILABLE` | 在**拉起服务端的同一环境**里确认 `grass` 可用，或设置 `GRASS_BRIDGE_BIN` 为完整路径。GUI 客户端的 PATH 可能与终端不同。 |
| `NOT_CONFIGURED` / `LOCATION_NOT_FOUND` / `MAPSET_NOT_FOUND` | 给服务端进程设置 `GRASS_BRIDGE_GISDBASE`，并核对 location/mapset 名与磁盘目录逐字一致。 |
| `CONFIRM_REQUIRED` | 执行/写类调用缺 `confirm=true`：先向用户说明要跑的作业与输出图层名，得到明确同意后再带上，不许自行补。 |
| `GRASS_FAILED` 且提示图层已存在 | 输出图层名与已有图层重名，GRASS 拒绝覆盖（桥不传 --overwrite）：换一个新的输出名，不要试图绕过。 |
| `OUTPUT_EXISTS`（export） | 导出路径已存在文件：换新文件名，桥不覆盖已有文件。 |
| `BAD_JOB` / `MISSING_PARAM` / `BAD_PARAMS` | 作业不在三个固定模板内，或参数缺失/多余：按 grass_discover 回报的 run_jobs 与模板改，不要发明新作业。 |
| 改了配置却像没生效 | MCP 客户端通常缓存已拉起的服务端进程；修改 env、token 或 gisdbase 后，重启服务端或重启客户端再试。 |
