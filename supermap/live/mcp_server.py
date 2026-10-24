# -*- coding: utf-8 -*-
"""
mcp_server.py — MCP 服务端（stdio，纯标准库，v0.3）

把 MCP 工具调用转发到 iDesktopX 内的应用内桥（inapp_bridge.py，127.0.0.1:47615）。
把本服务端注册到你的 AI Agent / MCP 客户端的 MCP 配置后，Agent 即可用下列工具
操作 iDesktopX 当前工作空间：
  只读：supermap_ping / supermap_discover / supermap_workspace_info /
        supermap_list_datasources / supermap_list_datasets / supermap_list_maps /
        supermap_list_layers / supermap_export_map_image
  视图级（只改显示、可逆）：supermap_set_layer_visible / supermap_zoom_to_dataset
  写类（须 confirm=true）：supermap_add_dataset_to_map / supermap_make_label_thematic /
        supermap_save_workspace
v0.3 的操作类工具为实验性实现，未在真实 iDesktopX 上验证；桥侧调不通时会
返回结构化错误，Agent 必须如实回报，不许把错误说成成功。

环境变量：
  SM_BRIDGE_HOST（默认 127.0.0.1）、SM_BRIDGE_PORT（默认 47615）、
  SM_BRIDGE_TOKEN（优先；否则读 ~/.supermap-live-bridge.token）
日志写 stderr，stdout 只走 MCP 协议。
"""
import json
import os
import socket
import sys

HOST = os.environ.get("SM_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("SM_BRIDGE_PORT", "47615"))
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".supermap-live-bridge.token")
PROTOCOL_VERSION = "2024-11-05"


def log(*a):
    print("[supermap-mcp]", *a, file=sys.stderr, flush=True)


def get_token():
    tok = os.environ.get("SM_BRIDGE_TOKEN")
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
    ("supermap_ping", "连通性检查：桥是否在线", {}),
    ("supermap_discover", "发现 iDesktopX 当前工作空间的接入方式并回报现场 API 信息（校准用）", {}),
    ("supermap_workspace_info", "当前工作空间概览：数据源数、地图数、接入模式", {}),
    ("supermap_list_datasources", "列出当前工作空间的全部数据源（别名、引擎）", {}),
    ("supermap_list_datasets", "列出数据集；可传 datasource 只看某数据源",
     {"datasource": dict(_STR, description="数据源别名（可选）")}),
    ("supermap_list_maps", "列出当前工作空间的全部地图名", {}),
    ("supermap_list_layers", "列出某地图的图层（下标、名称、显隐）；map 省略时取第一幅地图",
     {"map": dict(_STR, description="地图名（可选）")}),
    ("supermap_add_dataset_to_map", "【写·实验性】把数据集加入地图，须 confirm=true；调不通会如实报错",
     {"datasource": dict(_STR, description="数据源别名（可选）"),
      "dataset": dict(_STR, description="数据集名（必填）"),
      "map": dict(_STR, description="地图名（可选，省略取第一幅）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("supermap_set_layer_visible", "【视图级·实验性】设置图层显隐，只改显示状态、可逆",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示，false=隐藏")}),
    ("supermap_zoom_to_dataset", "【视图级·实验性】把地图视图缩放到数据集范围；做不到会报 NOT_SUPPORTED",
     {"datasource": dict(_STR, description="数据源别名（可选）"),
      "dataset": dict(_STR, description="数据集名（必填）"),
      "map": dict(_STR, description="地图名（可选）")}),
    ("supermap_make_label_thematic", "【写·实验性】按字段做标签专题图（如 NAME），须 confirm=true",
     {"map": dict(_STR, description="地图名（可选）"),
      "dataset": dict(_STR, description="数据集名（用于定位图层或新建专题图层）"),
      "layer": dict(_STR, description="已有图层名（可选，与 dataset 二选一优先）"),
      "field": dict(_STR, description="标签字段名（必填，如 NAME）"),
      "datasource": dict(_STR, description="数据源别名（可选）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("supermap_export_map_image", "【实验性】把地图导出为 PNG 到指定路径，以文件真实落盘为准",
     {"map": dict(_STR, description="地图名（可选）"),
      "out_path": dict(_STR, description="PNG 输出路径（必填，目录须已存在）"),
      "width": dict(_INT, description="宽度像素（可选）"),
      "height": dict(_INT, description="高度像素（可选）")}),
    ("supermap_save_workspace", "保存当前工作空间（写操作，必须 confirm=true）",
     {"confirm": dict(_BOOL, description="必须为 true 才执行")}),
]

BRIDGE_TOOL = {name: name.replace("supermap_", "", 1) for name, _, _ in TOOL_DEFS}


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
            "serverInfo": {"name": "supermap-live-bridge", "version": "0.3.0"}}}
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
