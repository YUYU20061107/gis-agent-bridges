# -*- coding: utf-8 -*-
"""
mcp_server.py — MCP 服务端（stdio，纯标准库，v0.1）

把 MCP 工具调用转发到 QGIS 内的应用内桥（inapp_bridge.py，127.0.0.1:47618）。
把本服务端注册到你的 AI Agent / MCP 客户端的 MCP 配置后，Agent 即可用下列工具
操作 QGIS 当前工程：
  只读：qgis_ping / qgis_discover / qgis_project_info / qgis_list_layers /
        qgis_list_layouts / qgis_list_fields / qgis_export_map_image
  视图级（只改显示、可逆）：qgis_set_layer_visible / qgis_zoom_to_layer
  写/执行类（须 confirm=true）：qgis_add_layer_from_path / qgis_run_processing /
        qgis_save_project
刻意不提供任意代码执行工具：qgis_run_processing 只接受算法 id + 参数 JSON。
v0.1 全部实时工具为实验性实现，未在真实 QGIS 上验证；桥侧调不通时会返回
结构化错误，Agent 必须如实回报，不许把错误说成成功。

环境变量：
  QGIS_BRIDGE_HOST（默认 127.0.0.1）、QGIS_BRIDGE_PORT（默认 47618）、
  QGIS_BRIDGE_TOKEN（优先；否则读 ~/.qgis-live-bridge.token）
日志写 stderr，stdout 只走 MCP 协议。
"""
import json
import os
import socket
import sys

HOST = os.environ.get("QGIS_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("QGIS_BRIDGE_PORT", "47618"))
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".qgis-live-bridge.token")
PROTOCOL_VERSION = "2024-11-05"


def log(*a):
    print("[qgis-mcp]", *a, file=sys.stderr, flush=True)


def get_token():
    tok = os.environ.get("QGIS_BRIDGE_TOKEN")
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
    with socket.create_connection((HOST, PORT), timeout=65) as s:
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
_OBJ = {"type": "object"}

TOOL_DEFS = [
    ("qgis_ping", "连通性检查：桥是否在线", {}),
    ("qgis_discover", "发现 QGIS 当前工程的接入方式并回报现场 API 信息（校准用）", {}),
    ("qgis_project_info", "当前工程概览：标题、文件路径、工程 CRS、图层数、接入模式", {}),
    ("qgis_list_layers", "列出当前工程的图层（名称、数据源、CRS、显隐；实时模式经图层树）", {}),
    ("qgis_list_layouts", "列出当前工程的打印布局名", {}),
    ("qgis_list_fields", "列出某矢量图层的字段（名称、类型、长度）",
     {"layer": dict(_STR, description="图层名、图层 id 或下标（必填）")}),
    ("qgis_set_layer_visible", "【视图级·实验性】设置图层显隐，只改显示状态、可逆",
     {"layer": dict(_STR, description="图层名、图层 id 或下标（必填）"),
      "visible": dict(_BOOL, description="true=显示，false=隐藏")}),
    ("qgis_zoom_to_layer", "【视图级·实验性】把画布缩放到图层范围；无画布时报 NOT_SUPPORTED 并附范围",
     {"layer": dict(_STR, description="图层名、图层 id 或下标（必填）")}),
    ("qgis_add_layer_from_path", "【写·实验性】按文件路径加载图层并加入当前工程，须 confirm=true",
     {"path": dict(_STR, description="图层文件路径（必填，须已存在）"),
      "name": dict(_STR, description="图层名（可选，默认取文件名）"),
      "provider": dict(_STR, description="数据提供者 ogr/gdal（可选，按扩展名推断）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("qgis_run_processing", "【执行·实验性】运行一个 Processing 算法，须 confirm=true；只接受算法 id + 参数，不提供任意代码执行",
     {"algorithm": dict(_STR, description="算法 id（必填，如 native:buffer）"),
      "parameters": dict(_OBJ, description="算法参数 JSON 对象（可选）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("qgis_export_map_image", "【实验性】导出地图/布局为图片到指定路径，以文件真实落盘且字节>0 为准",
     {"out_path": dict(_STR, description="图片输出路径（必填，目录须已存在）"),
      "layout": dict(_STR, description="打印布局名（可选，给了优先走布局导出）"),
      "width": dict(_INT, description="宽度像素（可选，渲染策略用）"),
      "height": dict(_INT, description="高度像素（可选，渲染策略用）"),
      "dpi": dict(_INT, description="布局导出 DPI（可选）")}),
    ("qgis_save_project", "保存当前工程（写操作，必须 confirm=true）；给 path 则另存为",
     {"path": dict(_STR, description="另存路径（可选）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
]

BRIDGE_TOOL = {name: name.replace("qgis_", "", 1) for name, _, _ in TOOL_DEFS}


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
            "serverInfo": {"name": "qgis-live-bridge", "version": "0.1.0"}}}
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
