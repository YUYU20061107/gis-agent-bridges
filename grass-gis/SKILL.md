# Skill: grass-headless-bridge（GRASS GIS 无头桥）

让 AI Agent 以无头批处理方式使用 GRASS GIS：看 location
与图层、取栅格信息、按三个固定作业模板跑处理（输出只能
是新图层）、把矢量图层导出为 GeoJSON 新文件。本包不是
GRASS GIS 官方组件；本 Skill 只提供有限、受控的动作，
动作之外不许自行发挥。

## 版本基线

- GRASS GIS 已安装、`grass` 启动器可用、已有一个 GRASS
  数据库（gisdbase）、Python 3.x（桥只用标准库）。
- 本包**未实机校准**：当前只有协议自检级证据（见 README
  「状态声明」）。在真实环境完成 `docs/CALIBRATION.md`
  之前，一切执行结果都按“模板已发出、语义待实机对账”
  口径回报，不许说成已验证可用。

## 运行前：token 与环境发现（每个新会话先做）

本包服务端**不会替调用方自动附带 `_token`**。每一次
tools/call（包括 `grass_ping` 与 `grass_discover`）都
必须在 `arguments` 里带 `_token`，否则 `BAD_TOKEN`。
token 只按以下来源取得，二者不要混用：

1. 若服务端进程设置了 `GRASS_BRIDGE_TOKEN`，使用该值；
   它优先于 token 文件；
2. 若未设置该环境变量，读取服务端 token 文件
   `~/.grass-agent-bridge.token`（Windows：
   `%USERPROFILE%\.grass-agent-bridge.token`）。两处都没
   有时，服务端会在启动时生成随机 token 并写入该文件。

真实 token 只用于调用，不许出现在回报、仓库文件或截图里。
取得 token 后再做环境发现：

1. 先带 `_token` 调 `grass_discover`：确认 grass 可用、
   gisdbase 已配置、目标 location 在清单里。要用的
   location/mapset/图层名都以 discover 与 list_maps 的
   回报为准，不许猜。
2. 跑任何执行/写类动作前，先用只读工具把输入图层与
   当前区域看清（list_maps、raster_info、location_info），
   并把要新建的输出图层名定下来，确认不与已有图层重名。

## 动作清单（v0.1，仅此这些）

```
grass_ping(_token=<token>)
grass_discover(_token=<token>)
grass_location_info(_token=<token>, location=<名>)
grass_list_maps(_token=<token>, location=<名>, mapset=<名>,
                type=<raster|vector|raster_3d|region 可选>)
grass_raster_info(_token=<token>, location=<名>, mapset=<名>,
                  map=<图层名>)
grass_run_module(_token=<token>, location=<名>, mapset=<名>,
                 job=<slope_aspect|hillshade|resample_nearest>,
                 params=<按作业模板>, confirm=true)
grass_export_vector(_token=<token>, location=<名>, mapset=<名>,
                    map=<图层名>, output=<.geojson 新文件路径>,
                    confirm=true)
```

- 作业参数模板：slope_aspect 需 elevation（输入）、
  slope 与 aspect（输出新名）；hillshade 需 input、
  output；resample_nearest 需 input、output。输出名不许
  带 @mapset，不许与已有图层重名（重名时 GRASS 会以
  未传 --overwrite 而失败，原样回报，不许换名自动重试
  掩盖——先向用户说明再定新名）。
- `confirm=true` 只能在向用户说明“跑哪个作业、输入什么、
  产出什么新图层”并得到明确同意后填入。没有同意就不跑，
  缺 confirm 被拒是正确行为，不是故障。
- export 的 output 必须是尚不存在的 .geojson 路径；
  落盘后回报 path 与 bytes，并用文件真实存在复核，
  不许只凭工具返回报成功。
- 导出的 GeoJSON 若要进桌面 GIS，用本仓 qgis/ 包的
  `qgis_add_layer_from_path` 加载，并按 qgis 包自己的
  校准口径回报。

## 安全纪律（硬规则，违反即停）

1. **没有任意模块**：不许要求、也不许尝试让桥执行六条
   模板之外的 GRASS 模块或自拼参数；桥拒绝（BAD_JOB /
   BAD_PARAMS / BAD_MAP_NAME）就是终局，回报用户决定，
   不许绕。
2. **永不覆盖**：不许以任何方式让桥传 --overwrite 或
   覆盖已有图层/文件；重名失败就是失败，先回报再定
   新名。
3. **区域与 mapset 自觉**：GRASS 作业受当前计算区域
   影响；桥不改区域设置。若结果范围与预期不符，先查
   location 的默认区域与 mapset 的 WIND，如实回报，
   不许私自改区域重跑凑结果。
4. **如实回报**：工具的 JSON 原文附在回报里；报错带
   error_code 与原始信息，不许把失败粉饰成成功，不许
   把协议自检说成实机校准。
5. **token 纪律**：`_token` 只从服务端 env 或 token
   文件取（env 优先）；每次 tools/call 都要显式附带。
   不许把真实值写进回报或仓库文件，也不许在
   `BAD_TOKEN` 后猜值重试。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `BAD_TOKEN` | 调用没带 `_token`，或值与服务端实际来源不一致 | 核对服务端是否设置了 `GRASS_BRIDGE_TOKEN`（它覆盖 token 文件）；否则读 token 文件；修正后重启服务端再调 |
| `CONFIRM_REQUIRED` | 执行/写类调用缺 confirm=true | 向用户说明作业与产出，得到明确同意后再带上，不许自行补 |
| `GRASS_NOT_AVAILABLE` | 本机没有 grass 或 GRASS_BRIDGE_BIN 指错 | 装 GRASS GIS 或修正路径，停 |
| `NOT_CONFIGURED` / `LOCATION_NOT_FOUND` / `MAPSET_NOT_FOUND` | gisdbase 未配或名字不对 | 核对 env 与磁盘目录，停 |
| `BAD_JOB` / `MISSING_PARAM` / `BAD_PARAMS` | 作业或参数不合模板 | 按 discover 的 run_jobs 与模板改，仍不对则停 |
| `GRASS_FAILED` | GRASS 侧报错（图层不存在、输出重名、区域问题等） | 带原始报错回报，不许改口径重跑凑绿 |
| `OUTPUT_EXISTS` / `EXPORT_NOT_LANDED` | 导出路径已存在 / 导出未落盘 | 换新文件名；未落盘带现场线索回报 |
| `GRASS_TIMEOUT` | 单次调用超 120 秒（或配置值） | 如实回报；大数据量作业先与用户商量分块口径，不许私自放宽超时重跑 |

## 回报格式

每次动作后回报：①一句话结论；②工具 JSON 原文；③涉及
执行/导出时，列出新产出的图层名或落盘文件路径与复核
结果；④若环境未过校准，注明“未实机校准”口径。没有
JSON 的回报视为未执行。
