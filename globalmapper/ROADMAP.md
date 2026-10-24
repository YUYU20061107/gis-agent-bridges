# ROADMAP —— globalmapper-bridge 演进与待校准清单

## 版本演进

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | 无头桥三件只读动作：preflight（模块/版本/候选命中预检）、backup（时间戳备份+sha256+引用文件提示）、inspect（模块打开临时副本盘点；模块不可用退化为 .gmw 文本部分解析）；校准探针 probe_api.py；MCP 服务端 7 工具（进程内直调模块，无常驻应用内桥；视图工具带上下文闸） | VM 侧已验证：脚本编译、selftest 5/5 PASS、backup 真复制+sha256、模块缺失环境报错 JSON 与退出码、inspect 退化解析链路；**与 Global Mapper 本体对接全部未实机验证** |

## 待实机校准清单（按依赖顺序）

1. **模块形态钉死**：目标机器上 globalmapper 模块的来源（Pro 版配套 Python
   环境 / 模块目录位置）、版本号取得方式（属性还是 GM_GetVersion 类函数），
   以及 probe 候选命中表与实际版本的对应关系。
2. **加载与枚举签名**：打开 .gmw 的真实函数（GM_LoadWorkspace / GM_LoadLayer /
   其他）与返回形态（单个 handle / handle 列表 / 错误元组）；图层枚举函数与
   “加载后枚举”是否需要同一会话句柄；图层名到底经 GM_GetLayerInfo 的哪个
   字段取得。无头 inspect 以此为准收紧。
3. **脚本上下文形态**：Script Editor 勾选 "Run Script in the Context of the
   Main View" 时，脚本进程与应用会话的关系——外部进程 import 模块能否看到
   应用已加载图层（discover 的 script-context-suspected 是否成立）、
   启动 MCP 服务端的正确姿势。结论决定方式 B 是否成立，不成立则以
   文件投递（方式 C）为正式通道。
4. **set_layer_visible**：显隐的真实函数与签名（Show/Hide 成对，还是
   Set...(handle, bool)），以及改完后主视图的刷新时机。
5. **zoom_to_layer**：公开脚本 API 是否存在缩放主视图的入口；若不存在，
   把 NOT_SUPPORTED 定为该版本的正式结论写回文档，不再重试其他歪路。
6. **export_workspace_image**：导出栅格的真实函数与参数（GM_ExportRaster 的
   签名/选项结构），以落盘+字节数>0 为准；顺带核对导出范围/分辨率参数。
7. 每个工具的命中策略（via）回写收紧：把多策略顺序按实机结果排序或删减，
   并在对应工具说明里注明实机版本（Global Mapper 版本 + 模块来源）。

## 后续候选（评估结论，均未实机验证）

- **文件投递通道产品化**：把 live/LIVE.md 方式 C 做成带序号、超时与结果
  校验的半自动作业通道（作业模板 + 结果 JSON 约定）。评估结论：**优先**——
  不依赖未校准的会话形态，是当前最稳的“半实时”路线。
- **.gms 脚本生成**：无 Python 模块的标准版环境下，由 Agent 生成
  Global Mapper 自有脚本语言（.gms）作业走文件投递。评估结论：可做，
  但标准版用户盘子有限，排在文件投递之后。
- **SDK（DLL）常驻桥**：用 Global Mapper SDK 在桌面端进程旁做常驻服务，
  争取真正的当前会话接入。评估结论：**成本高、后置**——SDK 是另一套
  授权与开发形态，且“常驻”仍不等于能拿到 GUI 主会话，未证明前不立项。
- **更多导出/批处理工具**（矢量导出、批量格式转换）：无头路线确定性高，
  待 v0.1 校准结论出来后按命中签名逐个加，仍守只读/只读出文件纪律。
