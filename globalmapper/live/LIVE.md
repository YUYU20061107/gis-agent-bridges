# 半实时工作方式说明（MCP 服务端 + 脚本上下文 / 文件投递，v0.1）

## 先认清形态：这是“半实时”，不是常驻实时桥

SuperMap / ArcGIS Pro 那类桥能在应用进程内常驻一个桥脚本，拿到“当前打开
的工程”实时操作。**Global Mapper 没有这种常驻形态**：它给脚本的只有
桌面 Script Editor——在编辑器里勾选 **"Run Script in the Context of the
Main View"** 运行的脚本，可以利用当前工作区已加载的图层。这只是
“半个会话”接口。本包的 MCP 服务端因此这样工作：

- 服务端在自己进程里直调 `globalmapper` 模块（无应用内桥、无推送）；
- 每次调用先探测运行上下文（context），并把 context 写进回报：
  - `headless`：外部 Python 运行，模块在位但没有应用已加载的图层；
  - `script-context-suspected`：模块的图层枚举候选报告出“本服务端没有
    加载过、但已经存在的图层”，疑似运行在应用会话旁；
  - `script-main-view`：启动方如实声明（环境变量
    `GM_BRIDGE_CONTEXT=main-view`）当前处于主视图脚本上下文。
- **视图类工具（显隐/缩放）只在后两种 context 下放行**，headless 下一律
  返回 `NOT_IN_MAIN_VIEW_CONTEXT`。声明必须属实：为了让工具放行而谎报
  main-view 属于造假，禁止（见 docs/CALIBRATION.md 红线）。

## 方式 A：无头 / 外部运行（默认）

1. 找一个能 import `globalmapper` 的 Python 解释器（先跑
   `scripts/probe_api.py` 确认命中表）。
2. 在你的 AI Agent / MCP 客户端里注册服务端：
   - command: 上一步的解释器
   - args: `<包路径>\live\mcp_server.py`
3. 可用能力：ping / discover / workspace_info / list_layers（传 workspace
   可先打开某个 .gmw）/ export_workspace_image。显隐与缩放会被上下文闸
   拒绝——这是设计，不是故障。

接入前先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list=7 / BAD_TOKEN 闸 / ping / discover，共 5 项，
全 PASS 只说明包本身没坏，不代表与 Global Mapper 本体已对接）。

## 方式 B：脚本上下文（半实时，主视图操作走这里）

1. 打开 Global Mapper Pro，打开工作区，确认图层已加载。
2. 打开 Script Editor，把一段“启动脚本”贴进去运行，脚本负责以 GM 的
   Python 环境拉起 `live/mcp_server.py`，并设置环境变量
   `GM_BRIDGE_CONTEXT=main-view`（仅在确实以主视图上下文运行时设置）。
   启动脚本的具体写法因 GM 版本而异，属校准项（见 docs/CALIBRATION.md
   第 3 步）；若某版本下模块在新进程里看不到应用已加载图层，
   discover 的 context_evidence 会暴露这一点，届时改走方式 C，不要硬闯。
3. Agent 侧照常经 MCP 调用；discover 应回报 context 为
   script-main-view 或 script-context-suspected，视图工具才可用。

## 方式 C：文件投递备选（最稳妥的降级通道）

当脚本上下文形态在当前版本走不通时，用文件投递，不要反复试探：

1. 约定一个作业目录（如 `<工作目录>\gm-jobs\`）与结果目录（`out\`）。
2. Agent 把要执行的操作写成一个 `.py`（用 globalmapper 模块）或 `.gms`
   作业文件放进作业目录，文件名带序号。
3. 用户在 Script Editor 里以主视图上下文打开并运行该作业文件；
   作业脚本把结果写成 JSON 放进 `out\` 同名文件。
4. Agent 读取结果 JSON 回报。没有 JSON 的作业视为未执行。

这条通道没有实时性，但每一步都有文件留档、可审计，且不依赖任何
未校准的会话形态。操作类作业同样受 SKILL.md 安全纪律约束
（先 backup、只改副本、写操作经用户当场确认）。

## 工具清单（v0.1，共 7 个）

风险等级：只读＝无副作用；只读出文件＝只往指定路径写导出文件；
视图级＝只改显示状态、可逆，但仅脚本上下文可用。

| 工具 | 作用 | 风险 |
|---|---|---|
| globalmapper_ping | 服务端是否在线、模块可用性、当前 context | 只读 |
| globalmapper_discover | 模块/版本/候选函数命中/context 与证据（校准用） | 只读 |
| globalmapper_workspace_info | 当前工作区概览（context、已打开工作区、图层数） | 只读 |
| globalmapper_list_layers | 列图层（名称、显隐可得时）；可传 workspace 先打开 | 只读 |
| globalmapper_export_workspace_image | 导出已加载图层为栅格图片（以文件真落盘为准） | 只读出文件 |
| globalmapper_set_layer_visible | 设置图层显隐（仅脚本上下文） | 视图级 |
| globalmapper_zoom_to_layer | 主视图缩放到图层范围（仅脚本上下文；可能 NOT_SUPPORTED） | 视图级 |

全部工具均为**未实机校准的实验性实现**：模块函数名/签名各版本差异大，
桥用多策略尝试并在结果里回报命中的函数名（via）；拿不到或不匹配时返回
结构化错误（NOT_SUPPORTED / *_FAILED / NOT_IN_MAIN_VIEW_CONTEXT，
附 attempts），这属于预期行为，Agent 必须如实回报，不许粉饰成成功。
首次实机校准按 `docs/CALIBRATION.md` 的顺序逐项进行。

## 纪律

- context 是判断“能不能碰主视图”的依据：headless 下被闸住就直说，
  按方式 B/C 处理，不许绕闸、不许谎报上下文。
- export_workspace_image 以“目标路径真有新文件落盘且字节数 > 0”为准，
  函数调用没报错但没文件 = 失败，如实回报。
- 如需给服务端加口令：启动前设置环境变量 `GM_BRIDGE_TOKEN`，
  之后每次 tools/call 必须在 arguments 里带 `_token` 且与之相等；
  token 不要发给任何人、不要写进作业文件留档。
- Global Mapper 里若弹出阻塞对话框，模块调用会挂起——先处理弹窗再继续，
  不要连环重试。

## 首次校准工单（给执行校准的 AI Agent，可直接粘贴）

> 按 `<包路径>\docs\CALIBRATION.md` 完成 Global Mapper 桥校准。目标结果：
> (1) scripts/probe_api.py 的候选命中表完整回传；(2) 无头 inspect 对一个
> 已知工作区的结果与界面逐项对上（或如实标注 partial-parse）；
> (3) discover 的 context 与证据如实回传，脚本上下文成立与否给出明确结论，
> 不许谎报 main-view；(4) 视图工具逐个有结论（可用附 via，不可用附
> attempts 原文）；(5) export 有落盘文件证据。全程对原件零写入，
> 除非我点名，不许调用 set_layer_visible / zoom_to_layer。
