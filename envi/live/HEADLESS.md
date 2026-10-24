# 为什么 ENVI 版只有无头桥（HEADLESS）

本系列其他成员（如 SuperMap、QGIS、ArcGIS Pro）的实时桥依赖一个共同前提：
宿主软件给进程内的脚本一个"当前会话"句柄——iDesktopX 的 Python 窗口能
拿到当前工作空间、QGIS 控制台有 `iface`、ArcGIS Pro 里有
`ArcGISProject("CURRENT")`。桥脚本驻留在宿主进程里，Agent 的每次操作
直接作用在用户正看着的那个工程上。

**ENVI 不满足这个前提：**

- ENVI 的本体 API 是 IDL 语言的 ENVITask 体系；官方给 Python 的通道是
  idlpy 桥（`from idlpy import IDL; e = IDL.ENVI(...)`），它启动的是
  **一个新的 ENVI 运行时会话**，而不是附着到用户已经打开的那个 ENVI
  桌面窗口。没有任何官方文档或接口声明支持"从外部 Python 接管已打开
  的 ENVI GUI 会话"。
- 因此，硬做"实时桥"只会得到一个名不副实的实现：Agent 操作的是它自起
  的会话，用户在 GUI 里什么都看不到，却以为在实时联动。本系列的纪律是
  **不许把文件回退或自起会话冒充实时接入**，所以本包明说：无头版，
  没有实时桥。

## 本包的会话模型

```
AI Agent ──stdio MCP──> mcp_server.py（宿主 Python）
                            ├─ .hdr 解析：不启会话，随读随算
                            └─ 惰性会话：第一次需要真跑任务时
                               IDL.ENVI(HEADLESS=1)，进程内复用
```

- 会话是**无头**的：没有窗口、没有视图，用户不要指望在 ENVI GUI 里
  看到任务过程；产出以任务输出文件与结构化回报为准。
- 会话只试启一次：许可或安装问题导致启动失败时，错误记入
  `ENVI_NOT_AVAILABLE` 如实回报，不反复重试（重试只会反复撞许可墙）。

## 那"实时"完全没戏吗？

有一条理论路线：用 **IDL 写一个驻留扩展（extension）**，让它在 ENVI
进程内开本地服务，转发 ENVITask 与当前视图对象。这要求桥的主体用 IDL
实现、随 ENVI 版本维护，成本与维护面都比其他成员高一个量级，且当前
没有实机条件验证。结论写在 ROADMAP.md：**后置，不排期**；在做到之前，
本包就只有一个诚实的无头版。

## 使用纪律

- 需要"看着影像做处理"的交互式工作，请直接用 ENVI GUI，不要让 Agent
  用无头会话猜你的视图状态。
- run_task 的输出路径请指向工作副本目录，输入栅格先用
  `scripts/envi_bridge.py backup` 留底（见 docs/CALIBRATION.md）。
