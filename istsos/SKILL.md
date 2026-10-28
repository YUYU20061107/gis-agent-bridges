# Skill: istsos-consumer-bridge（istSOS 消费侧只读桥）

让 AI Agent 以 OGC SensorThings API 只读方式从 STA 服务端取传感器
数据，并把观测导出为 GeoJSON，供桌面 GIS 工作流使用。首要对接目标
是 istSOS4，但本桥**不是 istSOS 官方组件**，只是标准协议的消费侧
客户端。本 Skill 只提供有限、受控的动作；动作之外不许自行发挥。

## 版本基线

- 任意符合 OGC SensorThings API 1.1 的服务端（istSOS4 优先验证目标，
  **目前未实测**，校准状态见 `docs/CALIBRATION.md`）。
- 桥本身：Python 3.x 纯标准库，无第三方依赖。
- 服务端形状与桥的假设不符时，先停下回报差异，不要硬跑。

## 运行前：环境发现（每个新会话先做一次）

1. 确认 `ISTSOS_BASE_URL` 已配置到目标 STA 服务端；未配置时
   业务工具只会回 `NOT_CONFIGURED`，不要换任何“默认地址”顶替。
2. 先调 `istsos_discover` 与 `istsos_ping`：discover 回报硬上限
   与校准口径，ping 确认服务端根路径可达；ping 不通先解决
   地址/网络，不许进入业务动作。
3. token 先行：本包的每次 tools/call（含上面第 2 步的
   discover/ping）都必须在 arguments 里带 `_token`。token
   来源：env `ISTSOS_BRIDGE_TOKEN`，或 token 文件（默认
   `~/.istsos-agent-bridge.token`；服务端启动时两者皆无会
   自动生成随机 token 并写入该文件）。完整调用长这样：

   ```json
   {"method": "tools/call", "params": {"name": "istsos_list_things", "arguments": {"_token": "<token 文件里那串，或 env 里设的值>", "top": 5}}}
   ```

   回 `BAD_TOKEN` 时先核对 token 来源与文件内容，不要绕过守卫。
4. 明确本次要看的 Datastream id 清单，不许对清单外的数据流
   擅自批量拉取。

## 动作清单（v0.1，仅此这些，全部只读）

### MCP 工具（live/mcp_server.py）

```
istsos_ping
istsos_discover
istsos_list_things            [top]
istsos_list_datastreams       [top] [thing_id]
istsos_get_observations       datastream_id [limit<=100]
istsos_export_observations_geojson  datastream_id [limit<=500] [directory]
```

- 列表类：`top` 是单页条数（默认 50、上限 100）；桥会跟随
  `@iot.nextLink` 但最多 3 页、总量 300 条，`truncated=true`
  表示还有更多没取完，引用数量时必须带上这个口径。
- `get_observations`：按 phenomenonTime 倒序返回最近观测；
  `limit` 默认 20、上限 100。超限会回 `LIMIT_EXCEEDED` 并拒绝，
  不许改小数字反复试探来“绕过”上限——要更多数据就分次取，
  或改用导出（上限 500）。
- `export_observations_geojson`：几何取 Datastream 所属 Thing 的
  第一个 Location，同一流全部观测共用该点位；**引用导出结果时
  必须说明这是站点点位、不是逐条观测的实测位置**。Thing 无位置
  时回 `NO_LOCATION` 且不生成文件，不许自行补坐标。
- 每次调用须带 `_token`（与服务端 env/token 文件一致），
  `BAD_TOKEN` 时先查 token 配置，不要绕过守卫。

## 禁止事项

- 不许声称 istSOS4 已验证/已校准——目前只有协议级自检
  （见 `docs/CALIBRATION.md`）；对 FROST 等其他 STA 实现的
  任何实测也不许说成 istSOS4 的结论。
- 不许对 STA 服务端发任何写请求；本桥没有写工具，发现自己在
  拼 POST/PUT/DELETE 就立即停下。
- 不许放宽代码里的硬上限常量来完成一次拉取；不够就分批，
  并如实回报 `truncated`。
- 不许把导出 GeoJSON 的共用点位说成每条观测各自的位置。
