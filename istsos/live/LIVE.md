# LIVE —— istSOS 消费侧只读桥运行说明

## 形态

stdio MCP 服务端（`live/mcp_server.py`），纯 Python 标准库。
与本合集的实时桥不同：本包没有常驻应用内桥、不占任何端口；
服务端进程只在被 MCP 客户端拉起时存在，对外只发 HTTP GET。

## 启动

```
# 必填：STA 服务端基地址（占位示例，非真实服务；末尾不带 /）
ISTSOS_BASE_URL=http://localhost:8080/istsos4/v1.1

# 可选：token（不设则启动时生成随机 token 写入 token 文件）
ISTSOS_BRIDGE_TOKEN=<your-token>
# 或 ISTSOS_BRIDGE_TOKEN_FILE=<path>（默认 ~/.istsos-agent-bridge.token）

# 可选：导出默认目录
ISTSOS_BRIDGE_OUTPUT_DIR=<dir>

python3 live/mcp_server.py
```

客户端配置示例见 `../examples/mcp-client-config.json`：把 env 段
里的 `ISTSOS_BASE_URL` 换成你的 STA 服务端地址；若不在 env 里给
token，服务端会把生成的随机 token 写到 token 文件，MCP 客户端侧
调用时把该 token 作为 `_token` 参数传入（具体传法见你的客户端/
Agent 约定）。

## 自检

```
python3 live/selftest.py   # 期望最后一行 SELFTEST: 12/12 PASS
```

自检自带一个跑在 127.0.0.1 随机端口的假 STA 服务端（回放固定
JSON），不需要任何真实服务、不出外网。自检通过只代表协议级
行为正确；校准状态与 istSOS4 实测流程见 `../docs/CALIBRATION.md`。

## 调用记录

每次 tools/call 向 `~/.istsos-agent-bridge/calls.jsonl` 追加一条
仅含工具名与成败的记录（不含观测数据），便于事后审计。
