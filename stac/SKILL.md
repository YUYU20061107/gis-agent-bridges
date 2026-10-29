# Skill: stac-consumer-bridge（STAC 消费侧只读桥）

让 AI Agent 在下载遥感影像之前，先只读地把 STAC 目录查
清楚：有哪些集合、时空范围与许可、某集合在指定范围内有
哪些景、云量多少；命中条目可导出成 GeoJSON 足印文件。
本包不是 STAC 官方组件；本 Skill 只提供有限、受控的
动作，动作之外不许自行发挥。

## 版本基线

- 一个可达的 STAC API 目录（支持 GET /search）、
  Python 3.x（桥只用标准库）。
- 本包**未实机校准**：当前只有协议自检级证据（见 README
  「状态声明」）。在真实目录完成 `docs/CALIBRATION.md`
  之前，一切检索结果都按“目录已应答、字段口径待实机
  对账”回报，不许说成已验证可用。

## 运行前：token 与环境发现（每个新会话先做）

本包服务端**不会替调用方自动附带 `_token`**。每一次
tools/call（包括 `stac_ping` 与 `stac_discover`）都必须
在 `arguments` 里带 `_token`，否则 `BAD_TOKEN`。token
只按以下来源取得，二者不要混用：

1. 若服务端进程设置了 `STAC_BRIDGE_TOKEN`，使用该值；
   它优先于 token 文件；
2. 若未设置该环境变量，读取服务端 token 文件
   `~/.stac-agent-bridge.token`（Windows：
   `%USERPROFILE%\.stac-agent-bridge.token`）。两处都没有
   时，服务端会在启动时生成随机 token 并写入该文件。

注意区分：桥 token 管的是“谁能调用桥”，目录的 API Key
（`STAC_API_KEY`）管的是“桥能不能读目录”，两者不可
互相替代，也都不许出现在回报、仓库文件或截图里。取得
token 后再做环境发现：

1. 先带 `_token` 调 `stac_discover` 与 `stac_ping`：确认
   基地址已配置、目录可达、目录 id 落档。ping 不通就
   停下回报，不许换着花样重试探活，更不许猜 token
   反复试。
2. 要检索的集合 id 先经 list_collections 看清再用，
   不许猜集合 id。
3. API Key 只经服务端进程环境提供；不许把 Key 写进任何
   文件、参数或回报文本。

## 动作清单（v0.1，仅此这些；全部只读远端）

```
stac_ping(_token=<token>)
stac_discover(_token=<token>)
stac_list_collections(_token=<token>)
stac_get_collection(_token=<token>, collection_id=<集合 id>)
stac_search_items(_token=<token>, collection_id=<集合 id>,
                  limit=<1..100 可选>, bbox=<[minlon,minlat,maxlon,maxlat] 可选>)
stac_export_items_geojson(_token=<token>, collection_id=<集合 id>,
                          limit=<1..500 可选>, bbox=<可选>,
                          directory=<可选>)
```

- 检索 count 为 0 就是该范围/集合下目录里没有条目，
  如实回报，不许放宽条件反复试探凑结果——真要扩大范围，
  先问用户。
- 云量等属性是目录自报：回报时注明来自目录元数据，
  不许当作实测值。
- 导出只含元数据与足印：回报时明确“不含影像本体”，
  不许把导出文件说成已经下载了影像。
- 资产下载不在本 Skill 范围内：用户要下数据时，回报
  集合许可与资产键名，建议其用自己的工具按许可下载，
  停下等用户决定。

## 安全纪律（硬规则，违反即停）

1. **只发 GET**：不许要求、也不许尝试让桥对目录做任何
   写操作或 POST 检索；桥没有这类通道，出现这类需求
   停下回报。
2. **不下资产、不抓任意 URL**：桥只拼固定模板路径；
   “顺便把这景数据下下来”不在范围内。
3. **如实回报**：工具的 JSON 原文附在回报里；报错带
   error_code 与原始信息，不许把失败粉饰成成功，不许
   把协议自检说成实机校准。
4. **token 纪律**：`_token` 只从服务端 env 或 token
   文件取（env 优先）；每次 tools/call 都要显式附带。
   不许把真实值写进回报或仓库文件，也不许在
   `BAD_TOKEN` 后猜值重试。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `BAD_TOKEN` | 调用没带 `_token`，或值与服务端实际来源不一致 | 核对服务端是否设置了 `STAC_BRIDGE_TOKEN`（它覆盖 token 文件）；否则读 token 文件；修正后重启服务端再调 |
| `NOT_CONFIGURED` | STAC_BASE_URL 未配置 | 让用户明确目录根地址后再查，停 |
| `HTTP_ERROR` 401/403 | 目录需要 API Key 或限制访问 | 让用户配 STAC_API_KEY 或确认目录开放政策，停 |
| `HTTP_ERROR` 404/405 | 集合不存在，或目录不支持 GET /search | 先 list_collections 对清 id；目录只支持 POST 检索时如实回报，不在本桥范围 |
| `LIMIT_EXCEEDED` | limit 超硬上限（检索 100 / 导出 500） | 减小 limit；不许分批绕过 |
| `BAD_BBOX` / `BAD_COLLECTION_ID` | 参数非法 | 按规则修正后重试一次，仍错则停 |
| `UNREACHABLE` / `RESPONSE_TOO_LARGE` | 目录不可达 / 响应超 2 MiB 上限 | 如实回报，不许放宽上限重试 |

## 回报格式

每次动作后回报：①一句话结论；②工具 JSON 原文；③涉及
导出时，列出落盘文件路径与 features 数复核结果；④若
环境未过校准，注明“未实机校准”口径。没有 JSON 的回报
视为未执行。
