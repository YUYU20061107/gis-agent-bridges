# 实机校准指南 —— globalmapper-bridge v0.1 校准与收紧

这是一份结果式校准指南，交给在实机上执行校准的 AI Agent：只描述要达成的结果、
验收标准与红线，具体做法由执行者决定；
但每一步的原始输出必须留档回传，没有 JSON 原文的回报视为未执行。

## 前提（不满足就停下回报，不要硬闯）

- 目标机器装有 **Global Mapper Pro**（标准版没有 globalmapper Python 模块，
  本包模块路线不成立，只能走文件投递生成 .gms 的降级讨论，不在本指南范围）。
- 校准用的工作区先经 `gm_bridge.py backup` 备份；一切操作类验证只在
  **工作区副本**上进行，原件零写入。

## 目标结果（全部达成才算完成）

1. `scripts/probe_api.py` 的候选命中表已钉死：每个功能组在本机版本上到底
   命中哪个函数名，无命中的组明确记为“无命中”，不许留“应该有”式结论。
2. 无头 inspect 对已知工作区给出与界面一致的图层清单（模块路线）；若只能
   退化到 partial-parse，如实标注并说明差在哪。
3. MCP 服务端的运行上下文有明确结论：脚本上下文（方式 B）成立或不成立，
   证据是 discover 的 context / context_evidence 原文；不许谎报 main-view。
4. 7 个 globalmapper_* 工具逐个有实机结论：可用（附命中 via 与回报 JSON）
   或不可用（附原始报错/ attempts），视图工具的结论注明当时的 context。
5. 校准结论回写进代码：命中策略按实机结果收紧排序，文档注明实机版本
   （Global Mapper 版本 + 模块来源），并跑一遍 `live/selftest.py`
   保持 5/5 PASS。

## 校准顺序（不要跳步）

1. **preflight + probe 钉死模块形态**：完整回传两份原文。据命中表判断
   加载/枚举/导出三组的主候选；三组全灭则停，先解决版本/模块来源问题。
2. **无头 inspect 对界面核对**：对已知工作区（副本）跑 inspect，
   图层名逐项与 Global Mapper 界面里看到的对上，留文字或截图证据；
   mode 为 headless-partial-parse 时，逐项标出与实际图层的差异。
3. **上下文校准**：按 live/LIVE.md 方式 B 尝试建立脚本上下文，
   回传 discover 全文。context 为 headless 且无任何预加载证据时，
   结论记为“方式 B 不成立”，改走文件投递（方式 C）验证一轮完整作业，
   不许设置 GM_BRIDGE_CONTEXT 造假。
4. **视图工具逐个验（只在副本工作区、且图层显隐后果可逆）**，顺序：
   export_workspace_image → set_layer_visible → zoom_to_layer。
   export 先行因为它只读出文件、且能证明“加载的图层就是界面的图层”。
5. **收紧与回归**：按命中策略改代码并注明版本；跑 selftest；
   把改动点逐条列清回传。

## 每项验收标准

- preflight：`globalmapper_import=ok`，module_version 非空或注明该版本无版本入口。
- probe：输出包含全部功能组的命中/未命中清单与模块公开名称全表。
- inspect（模块路线）：图层名、层数与界面一致；opened_via / name_via 已记录。
- inspect（退化路线）：gmw_header 与 referenced_files 与文件实际内容对得上，
  并明确记录图层名推测与界面实际名称的差异。
- discover：context 与 context_evidence 自洽（声明 main-view 时必须确有
  主视图上下文的启动事实支撑）。
- list_layers：workspace 参数打开副本后，清单与界面一致。
- export_workspace_image：目标路径真有图片落盘、字节数 > 0、能打开且
  内容是当前加载图层。
- set_layer_visible：界面上目标图层随开关显隐，visible_now（可得时）与设置值一致。
- zoom_to_layer：界面视图确实缩放到该图层范围；若全部候选失败，
  结论记 NOT_SUPPORTED 并附 attempts——这同样算完成校准，不许再发明歪路重试。

## 回报格式

每个工具一条：①一句话结论（可用/不可用）；②回报 JSON 原文；
③命中的策略（via 字段原文）；④界面证据（截图或具体文字）。
最后附：改动文件清单 + probe 输出原文 + selftest 输出原文 + 仍未解决项清单。

## 红线（违反任意一条立即停下回报）

- 对用户原始工作区零写入：校准只在 backup 后的副本上进行，原件修改时间可查。
- **不许伪造上下文**：GM_BRIDGE_CONTEXT 只能如实设置；为绕过上下文闸而
  谎报 main-view，视为校准造假，整轮结论作废。
- 不许为了让某个工具“通过”而临时加任意代码执行类工具或绕过 token 闸。
- 模块/版本报错即停，回报原文，不许换解释器、换环境反复试探（最多按
  SKILL.md 报错表处置一次）。
- 没有 JSON 原文的回报视为未执行；失败也要回传，不许只报结论。

## 从 SuperMap 实机校准迁移的通用教训（2026-10-24）

SuperMap 包已在 iDesktop 10i 上完成一轮实机校准（结论见 SuperMap 包的
`docs/CALIBRATION-RESULTS-20261024.md`）。其中与软件无关的通用教训已迁移
到本包；**本包自身仍未在真实 Global Mapper 上校准**，下表如实区分
“已落到代码/文档”与“仍是待本软件实机验证的假设”。

### 已落到本包代码 / 文档

| 教训（SuperMap 实测） | 本包落地形态 |
|---|---|
| Windows 下 `select()` 不能等子进程管道句柄（WinError 10038），须改后台线程 + 队列逐行读取 | `live/selftest.py` 已改用与 SuperMap 同款的 `_LineReader`（线程 + queue），删 `import select` |
| inspect 只复制工程文件会让相对路径数据源断链、盘点误报为空，须连带复制同目录数据源 | `scripts/verify_project.py --copy-to` 复制工程 + 同主名伴生 + 被引用数据的伴生集后对副本重开盘点；`gm_bridge.py inspect` 原有的临时副本逻辑与此一致 |
| 只读盘点 + 结构化报错 + issues 列表，是迁移验收的可靠形态；异常不许裸 traceback | 新增 `scripts/verify_project.py`：纯 Python 层盘点引用/伴生完整性，模块缺失时输出结构化 `GM_MODULE_NOT_AVAILABLE` 并 exit 1 |
| “假成功”真实存在：调用不报错 ≠ 效果落盘，须写后重读、以落盘文件为准 | 已写入 `ENGINEERING-PLAYBOOK.md` 第 4 节；`export_workspace_image` 的“落盘且字节>0 才算成功”口径与之同源（v0.1 已有） |
| 原件只读、先备份只改副本、相对路径风险、迁移验收清单等工程纪律与具体软件无关 | 已写入 `ENGINEERING-PLAYBOOK.md`（Global Mapper 适配版）第 1/2/3/7 节 |

注：SuperMap 的 token 文件机制（`SM_BRIDGE_TOKEN_FILE`）**未迁移**——本包
只用环境变量 `GM_BRIDGE_TOKEN` 传 token 值、无 token 文件，这是按本包
既有设计保留的差异，不视为缺口。

### 仍是待本软件实机验证的假设（不要当成结论）

- `globalmapper` 模块各功能组的真实函数名与签名（加载/枚举/图层名/显隐/
  缩放/导出候选表）全部仍是假设，靠 `scripts/probe_api.py` 在实机钉死。
- “脚本上下文能看到应用已加载图层”（discover 的 script-context-suspected
  判据）未验证；方式 B 不成立时按 CALIBRATION 顺序改走文件投递。
- 导出函数的落盘行为与参数形态、主视图刷新时机，均无实机证据。
- SuperMap 实测的若干软件专属事实（打开须接返回值、改图须 set_map 回写、
  专题须走特定入口等）**没有** Global Mapper 对应结论，不许类比套用；
  本软件若有同类坑，按本指南的校准顺序实测后另行记录。
