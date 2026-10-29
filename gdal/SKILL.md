# Skill: gdal-tool-bridge（GDAL/OGR 工具桥）

让 AI Agent 用 GDAL 命令行四件套探查栅格/矢量文件、取
波段统计，并在用户确认后做格式转换（只写新文件）。本
包不是 GDAL 官方组件；本 Skill 只提供有限、受控的动作，
动作之外不许自行发挥。

## 版本基线

- GDAL 命令行四件套已安装（同版本成套）、Python 3.x
  （桥只用标准库）。
- 本包**未实机校准**：当前只有协议自检级证据（见 README
  「状态声明」）。在真实环境完成 `docs/CALIBRATION.md`
  之前，一切探查/转换结果都按“模板已发出、真实 GDAL
  行为待实机对账”口径回报，不许说成已验证可用。

## 运行前：token 与环境发现（每个新会话先做）

本包服务端**不会替调用方自动附带 `_token`**。每一次
tools/call（包括 `gdal_ping` 与 `gdal_discover`）都
必须在 `arguments` 里带 `_token`，否则 `BAD_TOKEN`。
token 只按以下来源取得，二者不要混用：

1. 若服务端进程设置了 `GDAL_BRIDGE_TOKEN`，使用该值；
   它优先于 token 文件；
2. 若未设置该环境变量，读取服务端 token 文件
   `~/.gdal-agent-bridge.token`（Windows：
   `%USERPROFILE%\.gdal-agent-bridge.token`）。两处都没
   有时，服务端会在启动时生成随机 token 并写入该文件。

真实 token 只用于调用，不许出现在回报、仓库文件或截图里。
取得 token 后再做环境发现：

1. 先带 `_token` 调 `gdal_discover`：确认四件工具的
   路径、可用性与版本（四件应为同一 GDAL 版本；版本
   混杂先回报，不许带病转换），格式枚举以 discover
   回报为准。
2. 对任何要转换的文件，先跑只读探查看清它是什么
   （栅格用 raster_info＋按需 raster_stats，矢量用
   vector_info），再定输出名与格式。

## 动作清单（v0.1，仅此这些）

```
gdal_ping(_token=<token>)
gdal_discover(_token=<token>)
gdal_raster_info(_token=<token>, path=<本地栅格文件>)
gdal_vector_info(_token=<token>, path=<本地矢量文件>)
gdal_raster_stats(_token=<token>, path=<本地栅格文件>)
gdal_convert_raster(_token=<token>, path=<输入>, output=<新文件>,
                    format=<GTiff|PNG|JPEG>, confirm=true)
gdal_convert_vector(_token=<token>, path=<输入>, output=<新文件>,
                    format=<GeoJSON|GPKG>, confirm=true)
```

- 转换前先向用户复述“输入是什么、输出到哪、什么格式”，
  得到明确同意才填 `confirm=true`。没有同意就不转，
  缺 confirm 被拒是正确行为，不是故障。
- 输出名必须尚不存在且扩展名与格式匹配（GTiff 用
  .tif/.tiff，GeoJSON 用 .geojson/.json）；被
  OUTPUT_EXISTS 拒绝时先回报再定新名，不许删掉已有
  文件腾位置。
- 转换落盘后必须复核：对输出再跑一次对应的 info 工具，
  把驱动/尺寸或图层/要素数与输入对账后才报完成。
- 拿不准一个文件是栅格还是矢量时，先 raster_info，
  失败再 vector_info，两个都失败就带原始报错回报，
  不许猜。

## 安全纪律（硬规则，违反即停）

1. **没有选项透传**：不许要求、也不许尝试让桥执行五条
   模板之外的 GDAL 能力（重投影、裁剪、拼接、SQL 查询
   等）；被拒就是终局，回报用户决定，不许绕。
2. **只探查本地文件**：远程与 /vsi 路径一律不碰；需要
   探查网络数据时，先经用户同意下载到本地再探查，并
   在回报里注明来源。
3. **原件零副作用自觉**：桥已强制 GDAL_PAM_ENABLED=NO；
   若发现原件旁出现 .aux.xml 等伴生文件，说明有别的
   工具动过，如实回报，不许掩盖。
4. **永不覆盖**：不许以任何方式覆盖已有文件；输出重名
   就换新名并留档，不许删除或改名挪开已有文件。
5. **如实回报**：工具的 JSON 原文附在回报里；报错带
   error_code 与原始信息，不许把失败粉饰成成功，不许
   把协议自检说成实机校准。
6. **token 纪律**：`_token` 只从服务端 env 或 token
   文件取（env 优先）；每次 tools/call 都要显式附带。
   不许把真实值写进回报或仓库文件，也不许在
   `BAD_TOKEN` 后猜值重试。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `BAD_TOKEN` | 调用没带 `_token`，或值与服务端实际来源不一致 | 核对服务端是否设置了 `GDAL_BRIDGE_TOKEN`（它覆盖 token 文件）；否则读 token 文件；修正后重启服务端再调 |
| `CONFIRM_REQUIRED` | 转换调用缺 confirm=true | 向用户说明输入/输出/格式，得到明确同意后再带上，不许自行补 |
| `NOT_AVAILABLE` | 某件 GDAL 工具不可用 | 装 GDAL 或用 GDAL_BRIDGE_* 指定路径，停 |
| `PATH_NOT_FOUND` | 输入路径不存在 | 核对路径，停 |
| `REMOTE_PATH_REJECTED` | 输入是远程或 /vsi 路径 | 先下载到本地（经用户同意）再探查 |
| `PARSE_FAILED` | 探查输出解析不了（多为老版本无 -json） | 带原文回报，记录版本，停 |
| `GDAL_FAILED` | GDAL 侧报错（文件损坏、驱动不支持等） | 带原始报错回报，不许换工具硬凑 |
| `OUTPUT_EXISTS` / `OUTPUT_EXT_MISMATCH` / `OUTPUT_PARENT_MISSING` | 输出已存在 / 扩展名不符 / 父目录不存在 | 换新名、改扩展名或先建目录（经用户同意），再重试 |
| `CONVERT_NOT_LANDED` | 转换返回成功但输出不在 | 带现场线索回报，停 |
| `GDAL_TIMEOUT` | 单次调用超 60 秒（或配置值） | 如实回报；大文件先与用户商量，不许私自放宽重跑 |

## 回报格式

每次动作后回报：①一句话结论；②工具 JSON 原文；③涉及
转换时，列出输出路径、bytes 与复核探查的结果；④若
环境未过校准，注明“未实机校准”口径。没有 JSON 的回报
视为未执行。
