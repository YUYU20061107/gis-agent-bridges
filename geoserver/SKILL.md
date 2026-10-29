# Skill: geoserver-consumer-bridge（GeoServer 消费侧只读桥）

让 AI Agent 在调用 WMS/WFS 之前，先只读地把一个 GeoServer
的目录看清楚：工作区、图层、单图层详情（CRS、范围）与
GetCapabilities 摘要。本包不是 GeoServer 官方组件；本
Skill 只提供有限、受控的动作，动作之外不许自行发挥。

## 版本基线

- 一个可达的 GeoServer（REST 目录端点通常需要 Basic
  认证）、Python 3.x（桥只用标准库）。
- 本包**未实机校准**：当前只有协议自检级证据（见 README
  「状态声明」）。在真实环境完成 `docs/CALIBRATION.md`
  之前，一切目录结果都按“端点已应答、字段口径待实机对账”
  回报，不许说成已验证可用。

## 运行前：token 与环境发现（每个新会话先做）

本包服务端**不会替调用方自动附带 `_token`**。每一次
tools/call（包括 `geoserver_ping` 与 `geoserver_discover`）
都必须在 `arguments` 里带 `_token`，否则 `BAD_TOKEN`。
token 只按以下来源取得，二者不要混用：

1. 若服务端进程设置了 `GEOSERVER_BRIDGE_TOKEN`，使用该值；
   它优先于 token 文件；
2. 若未设置该环境变量，读取服务端 token 文件
   `~/.geoserver-agent-bridge.token`（Windows：
   `%USERPROFILE%\.geoserver-agent-bridge.token`）。两处都
   没有时，服务端会在启动时生成随机 token 并写入该文件。

真实 token 只用于调用，不许出现在回报、仓库文件或截图里。
取得 token 后再做环境发现：

1. 先带 `_token` 调 `geoserver_discover` 与
   `geoserver_ping`：确认基地址已配置、服务端可达、版本
   落档。ping 不通就停下回报，不许换着花样重试探活，更
   不许猜 token 反复试。
2. 认证变量只经服务端进程环境提供；不许把 GeoServer 的
   密码写进任何文件、参数或回报文本。401/403 是权限问题，
   回报用户处理，不许尝试绕过认证。
3. 要查的图层名先经 list_layers 看清全名（含工作区前缀）
   再查详情，不许猜图层名。

## 动作清单（v0.1，仅此这些；全部只读）

```
geoserver_ping(_token=<token>)
geoserver_discover(_token=<token>)
geoserver_list_workspaces(_token=<token>)
geoserver_list_layers(_token=<token>, workspace=<可选>)
geoserver_layer_info(_token=<token>, name=<workspace:name 或 name>)
geoserver_capabilities_summary(_token=<token>, service=<wms|wfs 可选>)
```

- `truncated=true` 就是目录超过 300 条被截断，如实回报，
  不许说成“全部图层”。
- layer_info 里出现 resource_note（href 不同源未跟随）时
  如实回报，不许自己拼 URL 去取。
- GetCapabilities 是服务端自报：标题与名字清单只能当作
  “服务端声称”，与 REST 目录对不上时以差异形式回报，
  不许替服务端圆场。

## 安全纪律（硬规则，违反即停）

1. **只发 GET**：不许要求、也不许尝试让桥对 GeoServer 做
   任何写操作（发布/删除图层、改样式、改配置）；桥没有
   这类工具，出现这类需求停下回报。
2. **不抓任意 URL**：桥只拼固定模板路径；任何“顺便打开
   这个链接看看”的要求都不在本 Skill 范围内。
3. **如实回报**：工具的 JSON 原文附在回报里；报错带
   error_code 与原始信息，不许把失败粉饰成成功，不许把
   协议自检说成实机校准。
4. **token 纪律**：`_token` 只从服务端 env 或 token 文件
   取（env 优先）；每次 tools/call 都要显式附带。不许把
   真实值写进回报或仓库文件，也不许在 `BAD_TOKEN` 后猜值
   重试。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `BAD_TOKEN` | 调用没带 `_token`，或值与服务端实际来源不一致 | 核对服务端是否设置了 `GEOSERVER_BRIDGE_TOKEN`（它覆盖 token 文件）；否则读 token 文件；修正后重启服务端再调 |
| `NOT_CONFIGURED` | GEOSERVER_BASE_URL 未配置 | 让用户明确基地址后再查，停 |
| `HTTP_ERROR` 401/403 | REST 目录需要认证或权限不足 | 让用户配认证变量或调整角色权限，停，不许绕 |
| `HTTP_ERROR` 404 | 路径不存在（多半是图层名不对） | 先 list_layers 看清全名，不许猜 |
| `BAD_NAME` | 工作区/图层名含非法字符 | 按 `[A-Za-z0-9_.-]` 与单冒号规则改名，停 |
| `UNREACHABLE` / `RESPONSE_TOO_LARGE` | 服务不可达 / 响应超 2 MiB 上限 | 如实回报，不许放宽上限重试 |
| `BAD_XML` | GetCapabilities 不是合法 XML | 带原始线索回报（可能返回的是异常页） |

## 回报格式

每次动作后回报：①一句话结论；②工具 JSON 原文；③若环境
未过校准，注明“未实机校准”口径。没有 JSON 的回报视为
未执行。
