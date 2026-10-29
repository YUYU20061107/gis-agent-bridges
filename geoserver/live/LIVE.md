# LIVE —— GeoServer 消费侧只读桥运行说明

## 形态

`live/mcp_server.py` 是纯 Python 标准库的 **stdio MCP 服务端**：

- 它没有常驻应用内桥，不监听任何 TCP 端口，也不提供 HTTP 服务
  （它作为客户端去连你的 GeoServer，那是另一回事）。
- MCP 客户端按需拉起这个进程，双方只通过 stdin/stdout 传 MCP
  JSON-RPC；stdout 是协议通道，运行日志只写 stderr。
- 服务端对 GeoServer 只发 GET：REST 目录端点与 OGC
  GetCapabilities；没有任何写通道。
- 六个工具全部只读远端，也不写本地文件（本包没有导出工具）。

首次使用前先看 `../README.md` 的定位与状态声明；接真实
GeoServer 后，校准顺序与验收口径以 `../docs/CALIBRATION.md`
为准。手动直接运行服务端时，它会静默等待 stdin 输入，这不是
卡死——它在等 MCP 客户端发 JSON-RPC 消息。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---:|---|
| `GEOSERVER_BASE_URL` | 业务工具必填 | GeoServer 基地址，形如 `http://localhost:8080/geoserver`，末尾不要带 `/` |
| `GEOSERVER_BRIDGE_TOKEN` | 否 | 若设置，服务端以它为期望 token，优先于 token 文件 |
| `GEOSERVER_USER` / `GEOSERVER_PASSWORD` | 否 | REST Basic 认证；密码只供请求头使用，桥不记录、不回显 |

注意进程归属：在终端里 `export` 的变量只对从该终端启动的
服务端与探针有效。若 Claude Desktop 等 GUI 客户端负责拉起
服务端，必须把同一组变量写进该客户端的 MCP 配置 `env` 段，
不能指望它继承另一个终端的 `export`。

## token 机制（调用方必须显式附带）

本包的 token 守卫常开：**服务端不会替调用方自动附带
`_token`**。`initialize`、`tools/list` 与协议 `ping` 不查
token；每一次 `tools/call`（包括本包的 `geoserver_ping` 与
`geoserver_discover`）都必须在 `arguments` 里亲自带上
`_token`，且与服务端期望值完全一致，否则返回 `BAD_TOKEN`。

服务端按以下顺序确定期望 token：

1. 若服务端进程环境里有非空的 `GEOSERVER_BRIDGE_TOKEN`，
   使用该值，不再看 token 文件；
2. 否则读取 token 文件：
   - Linux/macOS：`~/.geoserver-agent-bridge.token`
   - Windows：`%USERPROFILE%\.geoserver-agent-bridge.token`
3. 若环境变量未设、token 文件也不存在，服务端**启动时**生成
   一个随机 token，写入上述文件并尽量设为 0600，同时在
   stderr 打印文件路径。

不要把真实 token 写进仓库、客户端配置示例、提示词、回报或
截图；也不要靠反复猜测重试 `BAD_TOKEN`。

### 完整 tools/call 示例

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "geoserver_layer_info",
    "arguments": {
      "_token": "<TOKEN_FROM_ENV_OR_TOKEN_FILE>",
      "name": "topp:states"
    }
  }
}
```

## 启动与注册

手动启动（通常只用于确认进程能起来，实际使用由 MCP 客户端拉起）：

```bash
python3 live/mcp_server.py
```

客户端注册示例见 `../examples/mcp-client-config.json`；占位符
与跨平台 `command` 的替换方式集中写在 `../examples/prompts.md`。

调用日志在 `~/.geoserver-agent-bridge/calls.jsonl`，只记工具名
与成败，不记图层数据、密码与 token。

## 自检

```bash
python3 live/selftest.py
# 期望最后一行：SELFTEST: 12/12 PASS
```

自检用本地假 GeoServer 服务端验证协议、工具面与安全闸，不连接
真实 GeoServer。自检通过仍只是协议自检级证据，不是实机校准。

## 故障排查

| 现象 | 先查什么 |
|---|---|
| `BAD_TOKEN` | 是否**每一次** tools/call 都带了 `_token`；值是否与服务端进程实际使用的来源一致。只要服务端 env 里设置了 `GEOSERVER_BRIDGE_TOKEN`，它就覆盖 token 文件；改 env 或 token 后要重启服务端。 |
| 客户端列不出工具 | 先单独跑 `live/selftest.py`；再核对客户端配置中的 Python 命令与 `mcp_server.py` 绝对路径。手动启动后无输出是正常等待状态。 |
| `NOT_CONFIGURED` | 给服务端进程设置 `GEOSERVER_BASE_URL`。只在另一个终端 export、但 GUI 客户端没继承时，仍会报这个错。 |
| `HTTP_ERROR` 401/403 | GeoServer REST 目录端点通常需要认证：给服务端进程配 `GEOSERVER_USER` / `GEOSERVER_PASSWORD`（或确认匿名角色有目录读取权限）。桥不会替你绕过认证。 |
| `HTTP_ERROR` 404（layer_info） | 图层名拼写或工作区前缀不对；先用 list_layers 看清全名再查，不要猜。 |
| `BAD_NAME` | 工作区/图层名含非法字符（只许 `[A-Za-z0-9_.-]` 与一个冒号分隔）。 |
| layer_info 只有 resource_note | 服务端返回的 resource href 与基地址不同源，桥按防 SSRF 口径只回报未跟随；若那是预期的镜像地址，把 GEOSERVER_BASE_URL 改到同源地址再试。 |
| 改了配置却像没生效 | MCP 客户端通常缓存已拉起的服务端进程；修改 env、token 或基地址后，重启服务端或重启客户端再试。 |
