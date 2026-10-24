# 实时桥使用说明（iDesktopX 应用内桥 + MCP 接入，v0.3）

架构（同 Blender MCP 的模式）：
iDesktopX 进程内跑一个桥脚本（拿到当前工作空间）→ 本机 127.0.0.1:47615 →
MCP 服务端（stdio）→ 你的 AI Agent 调用工具直接操作你正开着的工程，界面实时可见。

## 启动三步

1. 打开 iDesktopX，打开要操作的工作空间与地图。
2. 打开 iDesktopX 的 Python 窗口，运行应用内桥：
   - 在 Python 窗口里执行：
     `exec(open(r"<包路径>\live\inapp_bridge.py", encoding="utf-8").read())`
   - 看到 `[supermap-live-bridge] listening on 127.0.0.1:47615` 即桥已上线；
     它同时把本次 token 写到 `~/.supermap-live-bridge.token`，MCP 服务端自动读取，无需手填。
3. 在你的 AI Agent / MCP 客户端的 MCP 配置中注册服务端（命令与参数按该客户端的配置格式填）：
   - command: 任意 Python 3 解释器（不需要装 iobjectspy，它只做转发）
   - args: `<包路径>\live\mcp_server.py`
   注册后客户端应能列出 13 个 supermap_* 工具。

接入前可先在任意 Python 3 里跑一遍 `live/selftest.py` 自检协议层
（initialize / tools/list / ping / discover / 保存闸门 / 错误 token 共 6 项，
全 PASS 才说明包本身没坏；它不验证与 iDesktopX 的对接）。

## 工具清单（v0.3，共 13 个）

风险等级：只读＝无副作用；视图级＝只改显示状态、可逆、不落盘；
写类＝改变工程内容，全部带 confirm=true 闸（confirm 只能在用户明确同意后填）。

| 工具 | 作用 | 风险 |
|---|---|---|
| supermap_ping | 桥是否在线 | 只读 |
| supermap_discover | 发现当前工作空间接入方式 + 现场 API 清单（校准用） | 只读 |
| supermap_workspace_info | 当前工作空间概览（数据源数/地图数/接入模式） | 只读 |
| supermap_list_datasources | 列数据源（别名、引擎） | 只读 |
| supermap_list_datasets | 列数据集（可按数据源别名过滤） | 只读 |
| supermap_list_maps | 列地图名 | 只读 |
| supermap_list_layers | 列某地图的图层（下标/名称/显隐） | 只读 |
| supermap_export_map_image | 导出地图为 PNG 到指定路径（以文件真落盘为准） | 只读出文件 |
| supermap_set_layer_visible | 设置图层显隐 | 视图级 |
| supermap_zoom_to_dataset | 地图视图缩放到数据集范围 | 视图级 |
| supermap_add_dataset_to_map | 把数据集加入地图（须 confirm=true） | **写** |
| supermap_make_label_thematic | 按字段做标签专题图（须 confirm=true） | **写** |
| supermap_save_workspace | 保存当前工作空间（须 confirm=true） | **写** |

v0.3 新增的 6 个工具（list_layers 起的后 6 个）为**实验性实现，未在真实
iDesktopX 上验证**：地图/图层/专题图/导出 API 各版本命名差异大，桥用多策略
尝试并在结果里回报命中的策略（via）；拿不到对象或 API 不匹配时返回结构化
错误（NOT_SUPPORTED / *_FAILED，附现场方法清单线索），这属于预期行为，
Agent 必须如实回报，不许粉饰成成功。首次实机校准按 `docs/CALIBRATION.md`
的顺序逐项进行（先 discover 钉死策略，操作工具只在工作空间副本上验）。

## 纪律

- 桥只监听 127.0.0.1 且带 token，不要改成对外监听，不要把 token 发给任何人。
- discover 的结果是判断"接入是否真的是 GUI 里那个工作空间"的依据：
  若 mode 显示 file-fallback，说明走的是文件回退，操作不会实时反映到界面，
  必须如实回报用户，不许说成实时接入。
- 写类工具的 confirm=true 只能在用户明确同意后由 Agent 填入，不许自作主张绕过。
- iDesktopX 里若弹出未保存提示等 GUI 阻塞，工具会超时——先处理弹窗再重试，不要连环重试。

## 首次校准工单（给执行校准的 AI Agent，可直接粘贴）

> 按 `<包路径>\live\LIVE.md` 启动实时桥并完成校准。目标结果：(1) supermap_ping 通；
> (2) supermap_discover 完整回报（mode、attempts、workspace_methods、map_class_methods、
> main_globals 原样回传）；(3) supermap_list_datasources、supermap_list_maps 与
> supermap_list_layers 的结果与 iDesktopX 界面里看到的一致，并截图或文字确认界面里
> 打开的正是同一个工作空间。mode 若为 file-fallback 就直说，不许报成实时接入成功。
> 全程除非我点名，不许调用任何写类工具（add_dataset_to_map、make_label_thematic、
> save_workspace）。后续逐项校准操作工具时改按 docs/CALIBRATION.md 执行。
