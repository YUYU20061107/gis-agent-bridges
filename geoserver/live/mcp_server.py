# -*- coding: utf-8 -*-
"""
mcp_server.py — GeoServer 消费侧只读桥 MCP 服务端（stdio，纯标准库，v0.1）

定位：本服务端不是 GeoServer 的组成部分，也不冒充 GeoServer 官方
组件。它是一个消费侧只读客户端：以只读方式从你自己的 GeoServer
取 REST 目录（工作区、图层、图层详情）与 OGC GetCapabilities
摘要，供 AI Agent 在动手调用 WMS/WFS 之前先把服务里有什么看
清楚。与 GeoServer / OSGeo 官方项目无隶属关系。

边界（刻意收窄）：
  - 对 GeoServer 只发 GET 请求；没有任何写工具，不创建/修改/
    删除任何远端实体；不提供任意代码执行或任意 URL 抓取工具。
  - 服务端基地址只从环境变量 GEOSERVER_BASE_URL 读，代码里不
    写死任何真实服务地址；未配置时业务工具返回 NOT_CONFIGURED。
  - 路径只由固定模板拼装；工作区名、图层名先经字符集校验再
    URL 编码。图层详情跟随的 resource href 按不可信输入处理，
    只有与基地址同源才跟随（防 SSRF 跳板）。
  - 防拉爆硬上限：单次响应读取 ≤ 2 MiB、请求超时 10 秒、列表
    返回 ≤ 300 条（REST 列表无服务端分页，本地截断并标注
    truncated=true，不假装给全）。
  - token 守卫（与本合集消费桥同口径）：环境变量
    GEOSERVER_BRIDGE_TOKEN 或 token 文件（默认
    ~/.geoserver-agent-bridge.token）给出期望 token；两者都
    没有时，服务端启动时生成一个随机 token 写入 token 文件。
    每次 tools/call 须在参数里带 _token 且一致，否则以
    BAD_TOKEN 拒绝。本服务端走 stdio、不监听任何网络端口。

环境变量：
  GEOSERVER_BASE_URL        GeoServer 基地址（必填，形如
                            http://localhost:8080/geoserver，
                            末尾不要带 /；占位示例、非真实服务）
  GEOSERVER_BRIDGE_TOKEN    token（优先于 token 文件）
  GEOSERVER_USER            REST 认证用户名（可选）
  GEOSERVER_PASSWORD        REST 认证密码（可选，只供请求头，
                            不进日志与回报）
每次 tools/call 都会向 ~/.geoserver-agent-bridge/calls.jsonl
追加一条仅含工具名与成败的调用记录（不记图层数据、不记密码）。
日志写 stderr，stdout 只走 MCP 协议。

校准状态（如实）：本包只过了本地假 GeoServer 服务端的协议级
自检（live/selftest.py）。真实 GeoServer 未实测。详见
docs/CALIBRATION.md。
"""
import io
import json
import os
import secrets
import sys
import urllib.parse
from datetime import datetime

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "geoserver-consumer-bridge"
SERVER_VERSION = "0.1.0"

TOKEN_FILE = os.path.join(os.path.expanduser("~"),
                          ".geoserver-agent-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"),
                           ".geoserver-agent-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "calls.jsonl")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))

import geoserver_bridge as gs  # noqa: E402


def log(*a):
    print("[geoserver-mcp]", *a, file=sys.stderr, flush=True)


# ---- 序列化净化（与仓内各包同口径） ----
try:
    _TEXT = unicode  # noqa: F821
except NameError:
    _TEXT = str


def _dec(b):
    if isinstance(b, _TEXT):
        return b
    if not isinstance(b, (bytes, bytearray)):
        return "%s" % (b,)
    try:
        return bytes(b).decode("utf-8")
    except Exception:
        pass
    for enc in (sys.getfilesystemencoding(), "gbk", "latin-1"):
        if not enc:
            continue
        try:
            return bytes(b).decode(enc)
        except Exception:
            continue
    return bytes(b).decode("utf-8", "replace")


def _to_text(obj):
    if isinstance(obj, dict):
        return dict((_to_text(k), _to_text(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [_to_text(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return _dec(obj)
    if obj is None or isinstance(obj, (_TEXT, bool, int, float)):
        return obj
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return "%s" % (obj,)


def _lock_stdio_utf8():
    for _name in ("stdout", "stdin"):
        _stream = getattr(sys, _name, None)
        _buf = getattr(_stream, "buffer", None)
        if _buf is None or getattr(_stream, "encoding", None) == "utf-8":
            continue
        try:
            setattr(sys, _name, io.TextIOWrapper(_buf, encoding="utf-8",
                                                 errors="replace"))
        except Exception:
            pass


# ------------------------------------------------------------------ token
def expected_token():
    tok = os.environ.get("GEOSERVER_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def ensure_token():
    """env 与 token 文件都没有 token 时，生成随机 token 写入文件
    （与本合集其他桥同口径）。返回生效 token。"""
    tok = expected_token()
    if tok:
        return tok
    tok = secrets.token_hex(16)
    try:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tok)
        log("generated bridge token at %s (0600)" % TOKEN_FILE)
    except Exception as e:
        log("WARNING: cannot write token file %s: %s" % (TOKEN_FILE, e))
    return tok


_ACTIVE_TOKEN = ""  # main() 启动时由 ensure_token() 赋值


def journal(entry):
    try:
        os.makedirs(JOURNAL_DIR, exist_ok=True)
        entry = dict(entry)
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _need_base():
    if gs.base_url() is None:
        return {"ok": False, "error_code": "NOT_CONFIGURED",
                "message": "未配置 GEOSERVER_BASE_URL，未发出任何请求；"
                           "请把 GeoServer 基地址写入该环境变量"
                           "（形如 http://localhost:8080/geoserver，"
                           "占位示例、非真实服务）"}
    return None


def _err(e):
    out = {"ok": False, "error_code": e.error_code, "message": e.message}
    if e.http_status is not None:
        out["http_status"] = e.http_status
    return out


# ------------------------------------------------------------------ tools
def tool_ping(args):
    info = {"ok": True, "pong": True, "bridge": SERVER_NAME,
            "version": SERVER_VERSION, "mode": "consumer-readonly",
            "base_url_configured": gs.base_url() is not None,
            "base_url": gs.base_url(),
            "auth_configured": gs.auth_configured()}
    err = _need_base()
    if err:
        info["server_reachable"] = False
        info["note"] = err["message"]
        return info
    try:
        data = gs.get_json("about/version.json")
        about = data.get("about") or {}
        info["server_reachable"] = True
        info["geoserver_version"] = about.get("Version")
        info["git_revision"] = about.get("Git Revision")
    except gs.BridgeError as e:
        info["server_reachable"] = False
        info["error_code"] = e.error_code
        info["note"] = e.message
        if e.http_status is not None:
            info["http_status"] = e.http_status
    return info


def tool_discover(args):
    return {"ok": True, "mode": "consumer-readonly",
            "server_name": SERVER_NAME, "version": SERVER_VERSION,
            "base_url": gs.base_url(),
            "base_url_configured": gs.base_url() is not None,
            "auth_configured": gs.auth_configured(),
            "token_guard": bool(_ACTIVE_TOKEN or expected_token()),
            "limits": {"max_list_items": gs.MAX_LIST_ITEMS,
                       "max_response_bytes": gs.MAX_RESPONSE_BYTES,
                       "http_timeout_s": gs.HTTP_TIMEOUT_S},
            "http_methods_used": ["GET"],
            "write_tools": [],
            "calibration_note": "仅协议级自检（本地假 GeoServer 服务端）；"
                                "真实 GeoServer 未实测，见 docs/CALIBRATION.md"}


def tool_list_workspaces(args):
    err = _need_base()
    if err:
        return err
    try:
        data = gs.get_json("workspaces.json")
    except gs.BridgeError as e:
        return _err(e)
    items, truncated = gs.cap_list(gs.parse_workspaces(data))
    return {"ok": True, "count": len(items), "workspaces": items,
            "truncated": truncated}


def tool_list_layers(args):
    err = _need_base()
    if err:
        return err
    workspace = args.get("workspace")
    if workspace is not None:
        try:
            gs.validate_segment(workspace, "workspace")
        except gs.BridgeError as e:
            return _err(e)
    try:
        data = gs.get_json("layers.json")
    except gs.BridgeError as e:
        return _err(e)
    items = gs.parse_layers(data)
    if workspace is not None:
        prefix = workspace + ":"
        items = [it for it in items
                 if (it.get("name") or "").startswith(prefix)]
    items, truncated = gs.cap_list(items)
    return {"ok": True, "count": len(items), "layers": items,
            "workspace_filter": workspace, "truncated": truncated}


def _bbox_view(node):
    if not isinstance(node, dict):
        return None
    return {"minx": node.get("minx"), "miny": node.get("miny"),
            "maxx": node.get("maxx"), "maxy": node.get("maxy"),
            "crs": node.get("crs")}


def tool_layer_info(args):
    err = _need_base()
    if err:
        return err
    try:
        name = gs.validate_layer_name(args.get("name"))
    except gs.BridgeError as e:
        return _err(e)
    try:
        data = gs.get_json("layers/%s.json"
                           % urllib.parse.quote(name, safe=":"))
    except gs.BridgeError as e:
        return _err(e)
    layer = data.get("layer") or {}
    info = {"ok": True, "name": layer.get("name") or name,
            "type": layer.get("type"),
            "default_style": (layer.get("defaultStyle") or {}).get("name"),
            "enabled": layer.get("enabled"),
            "queryable": layer.get("queryable")}
    resource = layer.get("resource") or {}
    info["resource_class"] = resource.get("@class")
    href = resource.get("href")
    info["resource_href"] = href
    if href and gs.same_origin(href):
        try:
            _ctype, raw = gs.http_get(href)
            detail = json.loads(raw.decode("utf-8"))
            body = detail.get("featureType") or detail.get("coverage") or {}
            info["resource"] = {
                "name": body.get("name"),
                "native_crs": body.get("nativeCRS") or body.get("srs"),
                "srs": body.get("srs"),
                "native_bbox": _bbox_view(body.get("nativeBoundingBox")),
                "latlon_bbox": _bbox_view(body.get("latLonBoundingBox")),
                "store": (body.get("store") or {}).get("name"),
            }
        except gs.BridgeError as e:
            info["resource_error"] = {"error_code": e.error_code,
                                      "message": e.message}
    elif href:
        info["resource_note"] = ("resource href 与基地址不同源，按不可信"
                                 "输入处理：只回报、未跟随")
    return info


def tool_capabilities_summary(args):
    err = _need_base()
    if err:
        return err
    service = args.get("service") or "wms"
    if service not in ("wms", "wfs"):
        return {"ok": False, "error_code": "BAD_SERVICE",
                "message": "service 只许 wms 或 wfs，收到 %r" % (service,)}
    if service == "wms":
        path = "wms?service=WMS&request=GetCapabilities&version=1.3.0"
    else:
        path = "ows?service=WFS&version=2.0.0&request=GetCapabilities"
    try:
        _ctype, raw = gs.http_get(gs.base_url() + "/" + path,
                                  accept="application/xml")
        summary = gs.parse_capabilities(raw, service)
    except gs.BridgeError as e:
        return _err(e)
    summary.update({"ok": True, "service": service,
                    "base_url": gs.base_url()})
    return summary


_STR = {"type": "string"}

TOOL_DEFS = [
("geoserver_ping",
"连通性检查：桥是否在线、GeoServer 基地址是否已配置、/rest/about/version 是否可达并回报服务端版本",
{}),
("geoserver_discover",
"环境发现：基地址、认证是否已配置（不报值）、硬上限、token 守卫与校准口径（校准用）",
{}),
("geoserver_list_workspaces",
"列出 GeoServer 的工作区名（REST /rest/workspaces.json）；上限 300 条，超限截断并标注",
{}),
("geoserver_list_layers",
"列出图层（name、type，REST /rest/layers.json）；传 workspace 只看该工作区前缀的图层；上限 300 条，超限截断并标注",
{"workspace": dict(_STR, description="工作区名（可选）：只返回该工作区前缀的图层")}),
("geoserver_layer_info",
"看一个图层的详情：类型、默认样式、可查询性，并跟随同源 resource 链接取其要素类型/覆盖的 CRS 与范围（bbox）",
{"name": dict(_STR, description="图层名（必填）：'name' 或 'workspace:name'")}),
("geoserver_capabilities_summary",
"取 WMS 或 WFS 的 GetCapabilities 并摘要：服务标题与图层/要素类型名清单（不回传整份 XML）",
{"service": dict(_STR, description="服务类型（可选）：wms（默认）或 wfs")}),
]

HANDLERS = {
"geoserver_ping": tool_ping,
"geoserver_discover": tool_discover,
"geoserver_list_workspaces": tool_list_workspaces,
"geoserver_list_layers": tool_list_layers,
"geoserver_layer_info": tool_layer_info,
"geoserver_capabilities_summary": tool_capabilities_summary,
}


def tools_list():
    out = []
    for name, desc, props in TOOL_DEFS:
        out.append({"name": name, "description": desc,
                    "inputSchema": {"type": "object",
                                    "properties": props}})
    return out


def _bad_token_reply(mid):
    payload = {"ok": False, "error_code": "BAD_TOKEN",
               "message": "token 缺失或不正确"}
    return {"jsonrpc": "2.0", "id": mid, "result": {
        "content": [{"type": "text",
                     "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": True}}


def _call_tool(mid, params):
    name = params.get("name")
    args = dict(params.get("arguments") or {})
    supplied = args.pop("_token", None)
    expect = _ACTIVE_TOKEN or expected_token()
    if expect and supplied != expect:
        return _bad_token_reply(mid)
    handler = HANDLERS.get(name)
    if handler is None:
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text",
                         "text": "unknown tool: %s" % name}],
            "isError": True}}
    try:
        result = handler(args)
        journal({"tool": name, "ok": bool(result.get("ok"))})
        text = json.dumps(_to_text(result), ensure_ascii=False, indent=2)
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": text}],
            "isError": False}}
    except Exception as e:
        journal({"tool": name, "ok": False, "error": str(e)})
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text",
                         "text": "tool failed: %s" % e}],
            "isError": True}}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME,
                           "version": SERVER_VERSION}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"tools": tools_list()}}
    if method == "tools/call":
        return _call_tool(mid, msg.get("params") or {})
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601,
                      "message": "method not found: %s" % method}}


def main():
    global _ACTIVE_TOKEN
    _lock_stdio_utf8()
    _ACTIVE_TOKEN = ensure_token()
    log("starting; base_url=%s token_guard=on journal=%s" % (
        gs.base_url() or "(not configured)", JOURNAL_FILE))
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
            sys.stdout.write(json.dumps(_to_text(resp),
                                        ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
