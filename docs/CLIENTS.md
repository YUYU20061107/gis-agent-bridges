# MCP 客户端接入指南

本仓的桥都是本机 stdio MCP 服务。接入分三步：生成配置片段、把片段放进
客户端的配置文件、重启客户端并验证工具清单。

## 1. 生成配置片段

在仓库根目录运行：

```bash
python scripts/quickstart.py --package qgis --print-config
```

把 `qgis` 换成目标包名。脚本只替换仓库根目录占位符，不替你改任何
客户端文件。包自己的原始模板在 `<package>/examples/mcp-client-config.json`。

需要注意：模板中的 `<ABSOLUTE_PATH_TO_PACKAGE>` 实际应替换为**仓库根目录**
的绝对路径，因为模板参数里已经带了 `<package>/live/mcp_server.py`。

## 2. 常见客户端配置文件位置

| 客户端 | 配置位置 | 顶层键 |
|---|---|---|
| Claude Desktop（Windows） | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers` |
| Claude Desktop（macOS） | `~/Library/Application Support/Claude/claude_desktop_config.json` | `mcpServers` |
| Cursor（项目级） | 项目目录 `.cursor/mcp.json` | `mcpServers` |
| Cursor（用户级） | `~/.cursor/mcp.json` | `mcpServers` |
| VS Code（工作区） | `.vscode/mcp.json` | `servers`（不是 `mcpServers`，粘贴时需改键名并按 VS Code 文档调整字段） |
| 其他 stdio MCP 客户端 | 以客户端文档为准 | 多数使用 `mcpServers` |

如果配置文件不存在，先在客户端设置里启用一次 MCP/开发者功能或手工
新建 JSON 文件。修改前先备份原配置；JSON 不允许尾随逗号。

Windows 上模板里的 `command` 通常是 `python`；若 `python` 指向商店
占位或找不到，请改成你实际 Python 3.11+ 的绝对路径。macOS/Linux
通常可把 `python` 改为 `python3`。厂商包要服从各包的解释器要求，
见根 README 的 Python 版本表。

## 3. 注册后验证

1. 完全退出并重启客户端（只关窗口可能不重读配置）。
2. 查看工具列表，数量应与 `manifest/tools-manifest.json` 一致：
   如 QGIS 12 个、pgRouting 5 个、istSOS 6 个。
3. 先调用该包的 `*_ping` 与 `*_discover`（如有），只做只读验证。
4. 桌面实时桥还要按包内 `live/LIVE.md` 在 GIS 软件内启动桥；只注册
   MCP 服务端不等于软件内桥已经运行。
5. pgRouting 与 istsos 是直接 stdio 消费桥，工具调用参数中还需要按
   各包 README/SKILL 的说明附当前 `_token`；桌面应用内桥则由服务端
   自动读取 token 文件，用户不需要手抄 token。

若工具数为 0、调用报 `BAD_TOKEN` 或客户端没有新工具，先看
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)。
