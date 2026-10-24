# gis-agent-bridges

A family of small, safety-gated bridges that let AI agents operate mainstream
GIS software — headless inventory/backup plus, where the vendor API allows, a
live in-app MCP bridge — all in one repo for easy reuse.

一个把主流 GIS 软件的「AI Agent 桥」收在一起的合集仓库：每个软件一个子目录，
形态统一为两种——**无头桥**（在软件进程外盘点、备份工程文件，只对副本动手），
以及在厂商 API 允许时的**应用内实时 MCP 桥**（桥脚本跑在软件进程内，Agent
经 MCP 协议操作你当前正打开的工程）。所有写操作都带确认闸，所有能力都如实标注。

## 项目由来

这两年，CAD、Blender 等工科软件陆续出现让 AI Agent 直接接入、操作当前工程
的服务，GIS/遥感这边基本还是空白。这个仓库想把主流 GIS 软件的桥都做出来、
放在一起，方便有需要的人直接取用——不管你手头是国产的 SuperMap、MapGIS，
还是 Esri 的 ArcGIS、开源的 QGIS，或是 ENVI、FME 这类处理工具。

## 软件矩阵

| 软件 | 目录 | 形态 | MCP 工具数 | 状态 |
|---|---|---|---|---|
| SuperMap iDesktopX | `supermap/` | 实时＋无头 | 13 | v0.4 · 文件回退模式已实机校准（iDesktop 10i，13/13）；iDesktopX 实时待验证；v0.4 增补工程文件生产手册、三维场景资产与验收脚本 |
| ArcGIS Pro | `arcgis-pro/` | 实时＋无头 | 13 | v0.1 · 未实机校准 |
| ArcMap（Esri 已退役，个人自用向） | `arcmap/` | 实时＋无头 | 10 | v0.1 · Python 2.7 待实机验证 |
| QGIS | `qgis/` | 实时＋无头 | 12 | v0.1 · 未实机校准 |
| GeoScene Pro（易智瑞） | `geoscene/` | 实时＋无头（ArcGIS Pro 同源衍生） | 13 | v0.1 · 兼容性待实机核验 |
| MapGIS（中地数码） | `mapgis/` | 探针＋无头骨架 | 3 | 探索版 · 实时接口未证实 |
| ENVI（NV5） | `envi/` | 仅无头 | 7 | v0.1 · idlpy 待实机 |
| Global Mapper（Blue Marble） | `globalmapper/` | 无头＋脚本半实时 | 7 | v0.1 · API 签名待探针 |
| FME（Safe Software） | `fme/` | 仅无头 runner | 6 | v0.1 · 与官方 Flow MCP 互补 |

## 统一设计原则

- **只在本机**：应用内桥只监听 127.0.0.1，每次启动生成随机 token，
  请求必须带对 token 才执行；token 只经本地文件在桥与 MCP 服务端之间传递。
- **写操作 confirm 闸门**：内容级写工具缺 `confirm=true` 一律拒绝执行；
  confirm 只能在用户明确同意后填入，Agent 不许自作主张绕过。
- **原件只读**：盘点与任何写需求都先 backup、只改副本，原件零写入。
- **不提供任意代码执行工具**：Agent 能做的事被限定在可枚举、可审计的
  工具集合内，没有 eval/exec 外部输入、任意脚本或任意处理工具调用的通道。
- **能力如实标注**：接入方式分模式回报——file-fallback 不冒充实时接入；
  无头模式只能读已保存状态；探针未证实的接口不假装存在，返回结构化错误
  并附现场线索。
- **先校准后使用**：每个包自带校准指南 `docs/CALIBRATION.md`，给出从探针
  钉死接入策略、只读工具逐项对界面、写操作只在副本上验的完整顺序与验收标准。

## 端口分配

| 端口 | 软件 |
|---|---|
| 47615 | SuperMap iDesktopX |
| 47616 | ArcGIS Pro |
| 47617 | ArcMap |
| 47618 | QGIS |
| 47619 | GeoScene Pro |

MapGIS、ENVI、Global Mapper、FME 无常驻应用内桥，不占端口。

## 快速开始

1. 进入你要用的软件对应的子目录。
2. 先读该包的 `README.md` 与 `SKILL.md`，弄清它的形态、工具清单与已知边界。
3. 跑该包的探针 / preflight 与 `live/selftest.py`，确认协议层与本机环境无误。
4. 按该包 `docs/CALIBRATION.md` 在真实软件上完成实机校准，通过后再正式使用。

## 状态与诚实声明

本仓所有包均**未在对应真实软件上完成实机校准**（每个包的 README 里有
各自的未验证清单）。已完成的是：协议层自检（initialize / 工具清单 /
保存闸门 / 错误 token 拒绝）与无头文件层（备份真复制、盘点的结构化报错等）
在无厂商软件环境中的验证。使用前请先按各包校准指南完成校准——
**不要把"协议自检通过"理解为"已与真实软件对接成功"**。

## 许可与免责

- 本仓库代码以 MIT 许可证发布（见根目录 `LICENSE`，各子包亦各带一份）。
- 本项目与 SuperMap、Esri、易智瑞、中地数码、NV5、Blue Marble Geographics、
  Safe Software 等厂商均无隶属关系，软件名称仅用于指明对接对象。
- 使用各桥需自备对应软件的正版许可；桥本身不包含、不分发任何厂商组件。
