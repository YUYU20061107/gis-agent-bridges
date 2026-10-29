# -*- coding: utf-8 -*-
"""
mcp_server.py — STAC 消费侧只读桥 MCP 服务端（stdio，纯标准库，v0.1）

定位：本服务端不是任何 STAC 服务端的组成部分，也不冒充其官方
组件。它是一个消费侧只读客户端：以 OGC STAC API 只读方式，从
任意符合 STAC API 规范的遥感影像目录取集合清单、集合详情与
影像条目检索结果，并可把检索结果导出成 GeoJSON 文件，供后续
桌面 GIS 工作流（例如经本合集的 QGIS 桥加载）使用。它与
STAC / OGC 官方项目无隶属关系。

边界（刻意收窄）：
  - 对 STAC 服务端只发 GET 请求（/search 用 GET 形态）；没有
    任何写工具；不跟随条目资产（assets）链接下载影像本体——
    资产只回报键名清单。
  - 服务端基地址只从环境变量 STAC_BASE_URL 读，代码里不写死
    任何真实服务地址；未配置时业务工具返回 NOT_CONFIGURED。
  - 防拉爆硬上限：单页检索 ≤ 100 条、导出 ≤ 500 条、集合
    列表跟随 next ≤ 3 页且总量 ≤ 300 条、单次响应读取
    ≤ 2 MiB、请求超时 10 秒。超限参数直接以 LIMIT_EXCEEDED
    拒绝，不静默截断；bbox 在本地先做范围与顺序校验。
  - token 守卫（与本合集其他桥同口径）：环境变量
    STAC_BRIDGE_TOKEN 或 token 文件（默认
    ~/.stac-agent-bridge.token）给出期望 token；两者都没有
    时，服务端启动时生成一个随机 token 写入 token 文件。
    每次 tools/call 须在参数里带 _token 且一致，否则以
    BAD_TOKEN 拒绝。本服务端走 stdio、不监听任何网络端口。

环境变量：
  STAC_BASE_URL             STAC API 根地址（必填，形如
                            https://example.org/stac，末尾不要
                            带 /；占位示例、非真实服务）
  STAC_BRIDGE_TOKEN         token（优先于 token 文件）
  STAC_API_KEY              目标目录要求 API Key 时经 Bearer
                            头发送（可选；不进日志与回报）
  STAC_BRIDGE_OUTPUT_DIR    导出 GeoJSON 的默认输出目录（可选）

每次 tools/call 都会向 ~/.stac-agent-bridge/calls.jsonl 追加
一条仅含工具名与成败的调用记录（不记影像数据）。日志写
stderr，stdout 只走 MCP 协议。

校准状态（如实）：本包只过了本地假 STAC 服务端的协议级自检
（live/selftest.py）。任何真实 STAC 目录都未实测。详见
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
SERVER_NAME = "stac-consumer-bridge"
SERVER_VERSION = "0.1.0"

TOKEN_FILE = os.path.join(os.path.expanduser("~"),
                          ".stac-agent-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"), ".stac-agent-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "calls.jsonl")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))

import stac_bridge as sb  # noqa: E402


def log(*a):
    print("[stac-mcp]", *a, file=sys.stderr, flush=True)


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
    tok = os.environ.get("STAC_BRIDGE_TOKEN")
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
    if sb.base_url() is None:
        return {"ok": False, "error_code": "NOT_CONFIGURED",
                "message": "未配置 STAC_BASE_URL，未发出任何请求；"
                           "请把 STAC API 根地址写入该环境变量"
                           "（形如 https://example.org/stac，"
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
            "base_url_configured": sb.base_url() is not None,
            "base_url": sb.base_url()}
    err = _need_base()
    if err:
        info["server_reachable"] = False
        info["note"] = err["message"]
        return info
    try:
        data = sb.http_get(sb.base_url())
        info["server_reachable"] = True
        info["catalog_id"] = data.get("id")
        info["catalog_title"] = data.get("title")
        info["conforms_to_count"] = len(data.get("conformsTo") or [])
        info["link_rels"] = sorted({lnk.get("rel") for lnk in
                                    (data.get("links") or [])
                                    if isinstance(lnk, dict)})
    except sb.BridgeError as e:
        info["server_reachable"] = False
        info["error_code"] = e.error_code
        info["note"] = e.message
    return info


def tool_discover(args):
    return {"ok": True, "mode": "consumer-readonly",
            "server_name": SERVER_NAME, "version": SERVER_VERSION,
            "base_url": sb.base_url(),
            "base_url_configured": sb.base_url() is not None,
            "api_key_configured": sb.api_key_configured(),
            "token_guard": bool(_ACTIVE_TOKEN or expected_token()),
            "limits": {"max_pages": sb.MAX_PAGES,
                       "max_list_items": sb.MAX_LIST_ITEMS,
                       "max_search": sb.MAX_SEARCH,
                       "default_search": sb.DEFAULT_SEARCH,
                       "max_export": sb.MAX_EXPORT,
                       "max_response_bytes": sb.MAX_RESPONSE_BYTES,
                       "http_timeout_s": sb.HTTP_TIMEOUT_S},
            "output_dir": os.environ.get("STAC_BRIDGE_OUTPUT_DIR")
                          or os.getcwd(),
            "http_methods_used": ["GET"],
            "write_tools": [],
            "calibration_note": "仅协议级自检（本地假 STAC 服务端）；"
                                "真实 STAC 目录未实测，见 docs/CALIBRATION.md"}


def tool_list_collections(args):
    err = _need_base()
    if err:
        return err
    try:
        items, meta = sb.fetch_collections()
    except sb.BridgeError as e:
        return _err(e)
    cols = [sb.trim_collection(c) for c in items]
    return {"ok": True, "count": len(cols), "collections": cols,
            "pages_fetched": meta["pages_fetched"],
            "truncated": meta["truncated"]}


def tool_get_collection(args):
    err = _need_base()
    if err:
        return err
    try:
        cid = sb.validate_collection_id(args.get("collection_id"))
        data = sb.http_get(sb.api_url("collections/%s"
                                      % urllib.parse.quote(cid, safe="")))
    except sb.BridgeError as e:
        return _err(e)
    result = {"ok": True}
    result.update(sb.trim_collection(data))
    result["keywords"] = data.get("keywords")
    result["stac_version"] = data.get("stac_version")
    return result


def _search_params(args, default_limit, max_limit):
    """解析检索公共参数；返回 (collection_id, limit, bbox, error)。"""
    try:
        cid = sb.validate_collection_id(args.get("collection_id"))
        limit = sb.validate_limit(args.get("limit"),
                                  default_limit, max_limit)
        bbox = None
        if args.get("bbox") is not None:
            bbox = sb.validate_bbox(args.get("bbox"))
    except sb.BridgeError as e:
        return None, None, None, _err(e)
    return cid, limit, bbox, None


def tool_search_items(args):
    err = _need_base()
    if err:
        return err
    cid, limit, bbox, err = _search_params(args, sb.DEFAULT_SEARCH,
                                           sb.MAX_SEARCH)
    if err:
        return err
    try:
        features = sb.search_items(cid, limit, bbox)
    except sb.BridgeError as e:
        return _err(e)
    items = [sb.trim_item(f) for f in features[:limit]]
    return {"ok": True, "collection_id": cid, "count": len(items),
            "items": items}


def tool_export_items_geojson(args):
    err = _need_base()
    if err:
        return err
    cid, limit, bbox, err = _search_params(args, 100, sb.MAX_EXPORT)
    if err:
        return err
    out_dir = args.get("directory") or \
        os.environ.get("STAC_BRIDGE_OUTPUT_DIR") or os.getcwd()
    try:
        features = sb.search_items(cid, limit, bbox)
    except sb.BridgeError as e:
        return _err(e)
    features = features[:limit]
    out_features = []
    for f in features:
        if not isinstance(f, dict):
            continue
        trimmed = sb.trim_item(f)
        props = {"id": trimmed["id"], "datetime": trimmed["datetime"],
                 "cloud_cover": trimmed["cloud_cover"],
                 "platform": trimmed["platform"],
                 "collection": trimmed["collection"],
                 "assets": trimmed["assets"]}
        out_features.append({"type": "Feature",
                             "geometry": trimmed["geometry"],
                             "properties": props})
    collection = {"type": "FeatureCollection", "features": out_features,
                  "properties": {
                      "source": "STAC API via %s %s"
                                % (SERVER_NAME, SERVER_VERSION),
                      "base_url": sb.base_url(),
                      "collection_id": cid,
                      "exported_at": datetime.now().isoformat(
                          timespec="seconds"),
                      "note": "只含条目元数据与足印几何，不含影像"
                              "数据本体；资产下载请按集合许可自行"
                              "进行"}}
    try:
        os.makedirs(out_dir, exist_ok=True)
        fname = "stac_items_%s_%s.geojson" % (
            cid, datetime.now().strftime("%Y%m%d-%H%M%S"))
        fpath = os.path.join(out_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(collection, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"ok": False, "error_code": "EXPORT_WRITE_FAILED",
                "message": "写出 GeoJSON 失败: %s" % e}
    return {"ok": True, "path": fpath, "collection_id": cid,
            "features": len(out_features)}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_ARR = {"type": "array", "items": {"type": "number"}}

_CID_PROP = dict(_STR, description="集合 id（必填）：只允许 "
                 "[A-Za-z0-9_.-]")
_BBOX_PROP = dict(_ARR, description="空间范围（可选）："
                  "[minlon, minlat, maxlon, maxlat] 四个数，"
                  "经纬度范围与顺序在本地先校验")

TOOL_DEFS = [
    ("stac_ping",
     "连通性检查：桥是否在线、STAC 基地址是否已配置、目录落地页是否可达（回报目录 id/标题与链接关系）",
     {}),
    ("stac_discover",
     "环境发现：基地址、API Key 是否已配置（不报值）、硬上限、token 守卫、导出目录与校准口径（校准用）",
     {}),
    ("stac_list_collections",
     "【只读】列出 STAC 目录的集合（id、标题、许可、时空范围、提供方）；跟随 next 上限 3 页/300 条，超限标注",
     {}),
    ("stac_get_collection",
     "【只读】看一个集合的详情摘要：许可、时空范围、提供方与关键词",
     {"collection_id": _CID_PROP}),
    ("stac_search_items",
     "【只读】按集合检索影像条目（GET /search）：回报 id、时间、云量、平台与资产键名；limit 上限 100，超限拒绝；可传 bbox 先本地校验",
     {"collection_id": _CID_PROP,
      "limit": dict(_INT, description="条数（可选，默认 20，范围 1..100）"),
      "bbox": _BBOX_PROP}),
    ("stac_export_items_geojson",
     "【只读远端·本地落文件】把按集合检索到的条目导出为 GeoJSON：足印几何＋元数据属性（不含影像本体）；limit 上限 500，超限拒绝",
     {"collection_id": _CID_PROP,
      "limit": dict(_INT, description="条数（可选，默认 100，范围 1..500）"),
      "bbox": _BBOX_PROP,
      "directory": dict(_STR, description="输出目录（可选，缺省用 "
                        "STAC_BRIDGE_OUTPUT_DIR 或当前目录）")}),
]

HANDLERS = {
    "stac_ping": tool_ping,
    "stac_discover": tool_discover,
    "stac_list_collections": tool_list_collections,
    "stac_get_collection": tool_get_collection,
    "stac_search_items": tool_search_items,
    "stac_export_items_geojson": tool_export_items_geojson,
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
        sb.base_url() or "(not configured)", JOURNAL_FILE))
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
