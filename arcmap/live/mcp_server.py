# -*- coding: utf-8 -*-
"""
mcp_server.py — MCP 服务端（stdio，纯标准库，Python 3，v0.2）

把 MCP 工具调用转发到 ArcMap 内的应用内桥（inapp_bridge.py，
127.0.0.1:47617）。本服务端跑在 ArcMap 进程之外，用任意 Python 3 即可，
不需要 arcpy——它只做转发。把本服务端注册到你的 AI Agent / MCP 客户端
的 MCP 配置后，Agent 即可用下列工具操作 ArcMap 当前打开的地图文档：
  只读：arcmap_ping / arcmap_discover / arcmap_document_info /
        arcmap_list_dataframes / arcmap_list_layers / arcmap_list_tables /
        arcmap_export_map_image
  视图级（只改显示、可逆）：arcmap_set_layer_visible / arcmap_zoom_to_layer
  写类（须 confirm=true）：arcmap_save_document
v0.2 未在真实 ArcMap 上验证（ArcMap 自带 Python 2.7，桥侧在实机窗口内的
行为属校准事项）；桥侧调不通时会返回结构化错误，Agent 必须如实回报，
不许把错误说成成功。

环境变量：
  ARCMAP_BRIDGE_HOST（默认 127.0.0.1）、ARCMAP_BRIDGE_PORT（默认 47617）、
  ARCMAP_BRIDGE_TOKEN（优先；否则读 ARCMAP_BRIDGE_TOKEN_FILE 指向的
  token 文件，默认 ~/.arcmap-live-bridge.token）
日志写 stderr，stdout 只走 MCP 协议。
"""
import json
import os
import socket
import sys

HOST = os.environ.get("ARCMAP_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ARCMAP_BRIDGE_PORT", "47617"))
# token 文件位置可用 ARCMAP_BRIDGE_TOKEN_FILE 覆盖（桥侧同名变量须一致）
TOKEN_FILE = os.environ.get("ARCMAP_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".arcmap-live-bridge.token")
PROTOCOL_VERSION = "2024-11-05"


def log(*a):
    print("[arcmap-mcp]", *a, file=sys.stderr, flush=True)


def get_token():
    tok = os.environ.get("ARCMAP_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def call_bridge(tool, args):
    payload = {"token": get_token(), "tool": tool, "args": args or {}}
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.create_connection((HOST, PORT), timeout=30) as s:
        s.sendall(data)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    resp = json.loads(buf.decode("utf-8"))
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error", "bridge error"))
    return resp.get("result")


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}

TOOL_DEFS = [
    ("arcmap_ping", "连通性检查：桥是否在线", {}),
    ("arcmap_discover", "发现 ArcMap 当前地图文档的接入方式并回报现场 API 信息（校准用）", {}),
    ("arcmap_document_info", "当前地图文档概览：路径、活动视图、页面大小、数据框/图层数、接入模式", {}),
    ("arcmap_list_dataframes", "列出全部数据框（名称、范围、比例尺、空间参考、图层数）", {}),
    ("arcmap_list_layers", "列出图层（名称、数据源、显隐、是否断裂）；可传 dataframe 只看某个数据框",
     {"dataframe": dict(_STR, description="数据框名（可选）")}),
    ("arcmap_list_tables", "列出文档中的独立表视图（名称、数据源）", {}),
    ("arcmap_set_layer_visible", "【视图级】设置图层显隐，只改显示状态、可逆",
     {"dataframe": dict(_STR, description="数据框名（可选，省略时跨框按名/全局下标查找）"),
      "layer": dict(_STR, description="图层名或全局下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示，false=隐藏")}),
    ("arcmap_zoom_to_layer", "【视图级】把数据框视图缩放到图层范围并刷新活动视图",
     {"dataframe": dict(_STR, description="数据框名（可选）"),
      "layer": dict(_STR, description="图层名或全局下标（数字字符串）")}),
    ("arcmap_export_map_image", "把当前文档导出为 PNG 到指定路径，以文件真实落盘为准",
     {"out_path": dict(_STR, description="PNG 输出路径（必填，目录须已存在）"),
      "resolution": dict(_INT, description="分辨率 DPI（可选，如 300）")}),
    ("arcmap_save_document", "保存当前地图文档（写操作，必须 confirm=true）",
     {"confirm": dict(_BOOL, description="必须为 true 才执行")}),
]

BRIDGE_TOOL = {name: name.replace("arcmap_", "", 1) for name, _, _ in TOOL_DEFS}


def tools_list():
    return [{"name": name,
             "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props in TOOL_DEFS]


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "arcmap-live-bridge", "version": "0.2.0"}}}
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
        if name not in BRIDGE_TOOL:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "unknown tool: %s" % name}],
                "isError": True}}
        try:
            result = call_bridge(BRIDGE_TOOL[name], args)
            text = json.dumps(result, ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "bridge call failed: %s" % e}],
                "isError": True}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    log("starting; bridge=%s:%d token_file=%s" % (HOST, PORT, TOKEN_FILE))
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
