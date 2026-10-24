---
name: supermap-gis-bridge
description: Use when the user asks to inspect, back up, or operate a SuperMap workspace/datasource (.smwu/.sxwu/.udbx), or asks for SuperMap iDesktopX live control (map export, layer visibility, zoom, label thematic, save). Bridges an AI agent to SuperMap through iobjectspy (headless) or an in-app live bridge; read-only by default, writes gated by confirm.
whenToUse: 盘点或备份 SuperMap 工程、对 iDesktopX 当前工作空间做地图级操作、排查 iobjectspy 与 iObjects Java 环境
---

> **实机验证状态（2026-10-24）**：已在一台 SuperMap **iDesktop 10i(2020)** 环境完成
> 第一轮实机校准（iObjects Java 10.1.0.19113、iobjectspy 10.1.0、iDesktop 自带
> Python 3.5.4 独立运行时）：
> - **无头桥已实机验证**：preflight / backup / inspect 三件套已对真实工作空间验证通过；
> - **实时桥 = `mode=file-fallback`**：该环境没有 iDesktopX，实时桥只能在**工作空间
>   副本**上运行，界面不会刷新，**不许报成实时接入**；13 个工具已全部实机验证
>   （含 3 个写类，写类均带 `confirm=true` 闸，只在用户明确同意后使用）；
> - 写操作落盘的关键：改完地图必须 `ws.set_map(name, map)` 回写（get_map 返回的是
>   包装副本）；标签专题必须走 `Map.add_dataset(dataset, layer_setting=ThemeLabel)`，
>   旧的专题设置路径是假成功（不渲染、不落盘）。
> 验证环境、13 工具清单、逐项结论与运行时搭建见 `docs/CALIBRATION-RESULTS-20261024.md`，
> 动手前必读；iDesktopX 实时模式仍待在有 X 的环境按校准工单继续校准。

# Skill: supermap-gis-bridge（SuperMap 工程文件桥接）

让 AI Agent 通过 SuperMap 官方 Python 组件 **iobjectspy** 操作 SuperMap 工程文件
（工作空间 *.smwu / *.sxwu、数据源 *.udbx），而不是直接读写二进制文件。
本 Skill 只提供有限、受控的动作；动作之外的一切操作（改数据、改符号、删图层）一律禁止自行发挥。

## 版本基线（开发基线）

- SuperMap iDesktop 10i（Windows），iObjects Java 10i，iobjectspy 10.x，Python 3.x，Java 8+。
- 若本机实际版本与上述不符，先停下回报版本差异，不要硬跑。

## 运行前：环境发现（每个新会话先做一次）

1. 定位 iDesktop 安装目录与 iObjects Java 的 Bin 目录（形如 `...\Bin_x64`）。
2. 定位一个装有 iobjectspy 的 Python 3 解释器（iDesktop 自带环境或用户指定的 conda 环境；
   **不要使用或修改与本任务无关的既有项目环境**）。
3. 运行预检（见下），预检不过不许进入任何业务动作。

## 动作清单（v0.1，仅此三项）

所有动作通过桥接脚本执行，脚本输出单行 JSON，必须原样附在回报里。

### 1) preflight —— 环境与许可预检（只读，无副作用）
```
<python> scripts/supermap_bridge.py preflight [--iobjects-java <Bin_x64路径>]
```
检查：Python 版本、iobjectspy 可导入、iObjects Java 路径已配置、许可冒烟
（构造一个 Workspace 对象即触发许可校验，出现 `hasp_container_not_found` 即许可不可用）。

### 2) backup —— 备份工作空间文件（只读原件）
```
<python> scripts/supermap_bridge.py backup <工作空间文件路径>
```
在同目录生成 `<原名>.bak-<yyyymmdd-HHMMSS><扩展名>` 副本并回报 sha256。
**任何写操作之前必须先 backup，且写操作只许作用于副本**（见安全纪律）。

### 3) inspect —— 工程盘点（只读）
```
<python> scripts/supermap_bridge.py inspect <工作空间文件路径>
```
脚本会先把工作空间复制到临时目录再打开（原件零接触），输出 JSON：
数据源别名/引擎、每个数据集的名称/类型/记录数（可得时）、地图名称与图层数（可得时）。
拿不到的字段为 null 并在 `notes` 里说明原因，不许猜。

### 校准探针 probe_api.py（仅首次部署或版本变更时运行一次）
```
<python> scripts/probe_api.py [工作空间路径]
```
输出本机 iobjectspy 的 Workspace/Datasource/Map 实际方法清单，供维护者据此收紧桥接脚本。
探针结果必须完整回传给用户/维护者，不得据此自行扩展动作。

## 安全纪律（硬规则，违反即停）

1. **原件只读**：禁止对用户指定的原始工作空间执行任何 save / 写入 / 删除动作。
   需要修改时，先 backup，再复制出一份工作副本，只改副本，并在回报中写明副本路径。
2. **禁止删除**任何数据集、图层、数据源；禁止批量改属性数据。v0.1 没有写动作，遇到
   需要写的需求，停下回报，不要临时写脚本凑。
3. **GUI 占用**：若工作空间正在 iDesktop 中打开，先请用户关闭或改走副本，不要强行打开。
4. **许可/版本错误即停**：许可报错、iobjectspy 与 iObjects Java 版本不匹配时，停下回报
   原始报错全文，不许换版本、换环境反复试（最多按报错表处置一次）。
5. **路径含中文/空格**一律用引号包裹并按原始字符串传参；JSON 输出保持 UTF-8 不转义。
6. 每一步的脚本原始输出（JSON）都要留档回传；失败也要回传，不许只报结论。

## 常见报错对照

| 现象 | 含义 | 处置 |
|---|---|---|
| `hasp_container_not_found` | SuperMap 许可不可用（未插锁/云许可未登录/许可服务未起） | 停。请用户检查许可后重跑 preflight |
| `ModuleNotFoundError: iobjectspy` | 当前解释器没装 iobjectspy | 换解释器（按“环境发现”顺序），不要 pip 装进无关的项目环境 |
| iobjectspy 与 iObjects Java 版本不一致类报错 | 组件版本不匹配 | 停，回报两边的实际版本号 |
| 打开工作空间超时/无响应 | 可能被 iDesktop 占用或文件损坏 | 先查 GUI 占用；再用 backup 副本重试一次，仍失败则停 |
| 工作空间打开但数据源为空/别名带感叹号语义 | 数据源文件被移动，连接失效 | 如实写入 inspect 的 notes，这正是盘点要发现的问题，不要自动修复 |

## 回报格式

每次动作后回报：①一句话结论；②脚本 JSON 原文；③若动过文件，列出新建文件路径清单。
没有 JSON 的回报视为未执行。
