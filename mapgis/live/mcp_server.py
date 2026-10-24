# -*- coding: utf-8 -*-
"""
mcp_server.py — MapGIS 探针 MCP 服务端（stdio，纯标准库，v0.1）

重要说明：MapGIS 的"应用内当前会话接口"未经证实，本包【没有】应用内桥，
本服务端也不连接任何 MapGIS 进程。它只把 scripts/probe_mapgis.py 的探测
能力包装成 3 个 MCP 工具，供 AI Agent / MCP 客户端在目标机器上先摸清环境：

  mapgis_ping               服务端是否在线（本地健康检查）
  mapgis_discover           探针结论摘要：是否找到 MapGIS Python 绑定
  mapgis_probe_environment  探针全量 JSON（安装目录、逐模块尝试、符号清单）

鉴权约定（与本系列其他桥保持一致的 token 纪律）：服务端启动时在
~/.mapgis-bridge.token 生成/读取本次 token；discover 与 probe_environment
调用时必须在 arguments 里带 token 字段且与文件一致，否则返回 BAD_TOKEN。
ping 为公开健康检查，不要求 token。等将来实时桥路线证实后，此约定平滑
迁移到桥侧握手。

日志写 stderr，stdout 只走 MCP 协议。
"""
import json
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import probe_mapgis  # noqa: E402

TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".mapgis-bridge.token")
PROTOCOL_VERSION = "2024-11-05"


def log(*a):
    print("[mapgis-mcp]", *a, file=sys.stderr, flush=True)


def ensure_token():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    except Exception:
        pass
    tok = secrets.token_hex(16)
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(tok)
    except Exception as e:
        log("cannot write token file:", e)
    return tok


TOKEN = ensure_token()

TOOL_DEFS = [
    ("mapgis_ping", "连通性检查：探针 MCP 服务端是否在线", {}),
    ("mapgis_discover",
     "探针结论摘要：本机是否存在可用的 MapGIS Python 绑定（须带 token）",
     {"token": {"type": "string", "description": "见 ~/.mapgis-bridge.token"}}),
    ("mapgis_probe_environment",
     "探针全量结果：安装目录启发式扫描、逐模块导入尝试、命中模块的符号与"
     "类方法清单（须带 token）。这是决定 MapGIS 桥接路线的立项依据。",
     {"token": {"type": "string", "description": "见 ~/.mapgis-bridge.token"}}),
]

TOOL_NAMES = {name for name, _d, _p in TOOL_DEFS}


def tools_list():
    return [{"name": name,
             "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props in TOOL_DEFS]


def run_tool(name, args):
    args = args or {}
    if name == "mapgis_ping":
        return {"pong": True, "server": "mapgis-probe-bridge/0.1",
                "live_bridge": None,
                "note": "本服务端只有探针工具，不连接任何 MapGIS 进程"}
    if args.get("token") != TOKEN:
        raise RuntimeError("BAD_TOKEN")
    probe = probe_mapgis.run_probe()
    if name == "mapgis_discover":
        found = probe.get("found") or {}
        return {
            "tool": "discover",
            "python_found": bool(probe["ok"]),
            "module": found.get("module"),
            "module_file": found.get("file"),
            "module_version": found.get("version"),
            "install_dirs_found": probe["install_dirs_found"],
            "modules_tried": len(probe["module_attempts"]),
            "error_code": probe.get("error_code"),
        }
    if name == "mapgis_probe_environment":
        return probe
    raise RuntimeError("unknown tool: %s" % name)


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mapgis-probe-bridge", "version": "0.1.0"}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools_list()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in TOOL_NAMES:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "unknown tool: %s" % name}],
                "isError": True}}
        try:
            result = run_tool(name, args)
            text = json.dumps(result, ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "tool call failed: %s" % e}],
                "isError": True}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    log("starting; token_file=%s" % TOKEN_FILE)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:
            log("bad json:", e)
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
