# -*- coding: utf-8 -*-
"""
mcp_server.py — MCP 服务端（stdio，纯标准库，v0.1）

把 MCP 工具调用转发到 GeoScene Pro 内的应用内桥（inapp_bridge.py，127.0.0.1:47619）。
把本服务端注册到你的 AI Agent / MCP 客户端的 MCP 配置后，Agent 即可用下列工具
操作 GeoScene Pro 当前打开的工程（与 ArcGIS Pro 的兼容性属同源推断，未经实机验证）：
  只读：geoscene_ping / geoscene_discover / geoscene_project_info / geoscene_list_maps /
        geoscene_list_layers / geoscene_list_tables / geoscene_list_layouts /
        geoscene_export_map_image
  视图级（只改显示、可逆）：geoscene_set_layer_visible / geoscene_zoom_to_layer /
        geoscene_set_labels_visible
  写类（须 confirm=true）：geoscene_add_layer_from_path / geoscene_save_project
工具面刻意收窄：不提供任意代码执行、任意 GP 工具调用类工具（有意的安全取舍）。
v0.1 的实时桥为实验性实现，未在真实 GeoScene Pro 上验证；桥侧调不通时会返回
结构化错误，Agent 必须如实回报，不许把错误说成成功。

环境变量：
  GEOSCENE_BRIDGE_HOST（默认 127.0.0.1）、GEOSCENE_BRIDGE_PORT（默认 47619）、
  GEOSCENE_BRIDGE_TOKEN（优先；否则读 ~/.geoscene-live-bridge.token）
日志写 stderr，stdout 只走 MCP 协议。
"""
import json
import os
import socket
import sys

HOST = os.environ.get("GEOSCENE_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("GEOSCENE_BRIDGE_PORT", "47619"))
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".geoscene-live-bridge.token")
PROTOCOL_VERSION = "2024-11-05"


def log(*a):
    print("[geoscene-mcp]", *a, file=sys.stderr, flush=True)


def get_token():
    tok = os.environ.get("GEOSCENE_BRIDGE_TOKEN")
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
    ("geoscene_ping", "连通性检查：桥是否在线", {}),
    ("geoscene_discover", "发现 GeoScene Pro 当前工程的接入方式并回报现场 API 信息（含产品身份字段，校准/兼容性核验用）", {}),
    ("geoscene_project_info", "当前工程概览：文件路径、默认地理数据库、地图数/布局数、接入模式", {}),
    ("geoscene_list_maps", "列出当前工程的全部地图（名称、类型）", {}),
    ("geoscene_list_layers", "列出某地图的图层（下标、名称、显隐、数据源、是否断裂）；map 省略时取第一幅地图",
     {"map": dict(_STR, description="地图名（可选）")}),
    ("geoscene_list_tables", "列出某地图的独立表（名称、数据源、是否断裂）；map 省略时取第一幅地图",
     {"map": dict(_STR, description="地图名（可选）")}),
    ("geoscene_list_layouts", "列出当前工程的全部布局（名称、页面宽高、地图框数）", {}),
    ("geoscene_set_layer_visible", "【视图级·实验性】设置图层显隐，只改显示状态、可逆",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示，false=隐藏")}),
    ("geoscene_zoom_to_layer", "【视图级·实验性】把活动视图缩放到图层范围；做不到会报 NOT_SUPPORTED",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）")}),
    ("geoscene_set_labels_visible", "【视图级·实验性】开关图层标注显示，只改显示状态、可逆",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示标注，false=关闭标注")}),
    ("geoscene_add_layer_from_path", "【写·实验性】把数据路径（要素类/shp/栅格等）加入地图，须 confirm=true；调不通会如实报错",
     {"map": dict(_STR, description="地图名（可选，省略取第一幅）"),
      "path": dict(_STR, description="数据路径（必填）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("geoscene_export_map_image", "【实验性】把布局（或其地图框）导出为 PNG 到指定路径，以文件真实落盘为准",
     {"layout": dict(_STR, description="布局名（可选；工程内只有一个布局时可省略）"),
      "map": dict(_STR, description="地图名（可选）"),
      "out_path": dict(_STR, description="PNG 输出路径（必填，目录须已存在）"),
      "resolution": dict(_INT, description="导出分辨率 DPI（可选，默认 200）"),
      "width": dict(_INT, description="宽度像素（可选，地图框导出变体用）"),
      "height": dict(_INT, description="高度像素（可选，地图框导出变体用）")}),
    ("geoscene_save_project", "保存当前工程（写操作，必须 confirm=true）",
     {"confirm": dict(_BOOL, description="必须为 true 才执行")}),
]

BRIDGE_TOOL = {name: name.replace("geoscene_", "", 1) for name, _, _ in TOOL_DEFS}


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
            "serverInfo": {"name": "geoscene-live-bridge", "version": "0.1.0"}}}
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
