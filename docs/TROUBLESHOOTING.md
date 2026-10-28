# 故障排查与求助

先做最小复现：确认你运行的是哪个包、哪种模式（无头/实时/消费侧），
把客户端日志与桥的自检结果分开看。协议自检失败是协议层问题；自检
通过但真实软件里不动，通常是软件内桥、许可、工程状态或校准问题。

## 快速分诊

| 现象 | 先查什么 |
|---|---|
| 客户端里没有工具 | 配置文件放错位置、JSON 语法错误、改完没完全重启客户端；再用 `scripts/quickstart.py --package <包> --print-config` 对照生成片段 |
| `python` 找不到 | Windows 改用 Python Launcher `py -3` 或 Python 3.11+ 绝对路径；macOS/Linux 常用 `python3`。厂商运行时例外见根 README 的版本表 |
| 自检都跑不起来 | 在包目录运行 `python live/selftest.py`，记录 Python 版本与第一条报错；仓库级工具要求 Python 3.11+ |
| `BAD_TOKEN` | 桌面桥：确认软件内桥已启动、token 文件路径与客户端 env 一致；pgRouting/istsos：确认工具参数带了当前 token 文件中的 `_token`，不要把旧 token 写死在提示词里 |
| 端口被占用 | 47615–47619 只应由对应桌面桥监听；先查哪个进程占用，不要同时启动两份同一桥 |
| 工具能列出但真实工程没反应 | 可能只启动了 MCP 服务端、没启动软件内桥；按该包 `live/LIVE.md`（ENVI 为 `HEADLESS.md`、FME 为 `RUNNER.md`）操作 |
| pgRouting 报 `PSQL_NOT_AVAILABLE` | 安装 PostgreSQL 客户端或用 `PGROUTING_PSQL` 指向 `psql`；再跑 `pgrouting/scripts/probe_api.py` |
| pgRouting 报 `NOT_CONFIGURED` / `TABLE_NOT_ALLOWED` | 设置 `PGROUTING_ALLOWED_TABLES`，且表名必须在允许集合内；桥不会猜表 |
| istsos 报 `NOT_CONFIGURED` | 设置 `ISTSOS_BASE_URL`；先跑 `istsos/scripts/probe_api.py` 做只读 GET 探针 |
| 导出文件找不到 | 看工具回报的绝对路径与导出目录；导出工具只写新文件，不会把结果自动加载进 GIS，需再用 GIS 包打开 |

## 求助时请附

使用 GitHub Issue 模板，并写清：

- 包名与模式、仓库 Release 或提交号；
- 操作系统、Python 版本、GIS 软件与版本、MCP 客户端与版本；
- 你运行的命令、自检输出、结构化错误码（如 `BAD_TOKEN`）；
- 是否能在仓内样本数据上复现。

**必须删掉**真实 token、数据库密码、API Key、私人工程绝对路径和未脱敏
日志。安全问题不要走普通 Issue，按根目录 `SECURITY.md` 的私密报告路径。
