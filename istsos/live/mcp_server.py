# -*- coding: utf-8 -*-
"""
mcp_server.py — istSOS 消费侧只读桥 MCP 服务端（stdio，纯标准库，v0.1）

定位：本服务端**不是** istSOS 的组成部分，也不冒充 istSOS 官方组件。
它是一个消费侧只读客户端：以 OGC SensorThings API（STA）只读方式，从
任意 STA 服务端取 Things / Datastreams / Observations，并可把观测导出
成 GeoJSON 文件，供后续桌面 GIS 工作流（例如经本合集的 QGIS 桥加载）
使用。首要对接目标是 istSOS4，但凡是符合 STA 1.1 的服务端都可连。

边界（刻意收窄）：
  - 对 STA 服务端只发 GET 请求；没有任何写工具，不创建/修改/删除
    任何远端实体；不提供任意代码执行或任意 URL 抓取工具。
  - 服务端基地址只从环境变量 ISTSOS_BASE_URL 读，代码里不写死任何
    真实服务地址；未配置时业务工具返回 NOT_CONFIGURED。
  - 防拉爆硬上限：单页 $top ≤ 100、列表跟随 nextLink ≤ 3 页且总量
    ≤ 300 条、get_observations ≤ 100 条、导出 ≤ 500 条、单次响应
    读取 ≤ 2 MiB、请求超时 10 秒。超限参数直接以 LIMIT_EXCEEDED 拒绝，
    不静默截断。
  - token 守卫（与本合集其他桥同口径）：环境变量 ISTSOS_BRIDGE_TOKEN
    或 token 文件（默认 ~/.istsos-agent-bridge.token）给出期望 token；
    两者都没有时，服务端启动时生成一个随机 token 写入 token 文件。
    每次 tools/call 须在参数里带 _token 且一致，否则以 BAD_TOKEN 拒绝。
    本服务端走 stdio、不监听任何网络端口；请勿把它改造成网络服务。

环境变量：
  ISTSOS_BASE_URL           STA 服务端基地址（必填，形如
                            http://localhost:8080/istsos4/v1.1，
                            末尾不要带 /；这里只是占位示例，不是真实服务）
  ISTSOS_BRIDGE_TOKEN       token（优先于 token 文件）
  ISTSOS_BRIDGE_TOKEN_FILE  token 文件路径（可选）
  ISTSOS_BRIDGE_OUTPUT_DIR  导出 GeoJSON 的默认输出目录（可选）

每次 tools/call 都会向 ~/.istsos-agent-bridge/calls.jsonl 追加一条
仅含工具名与成败的调用记录（不记观测数据）。日志写 stderr，
stdout 只走 MCP 协议。

校准状态（如实）：本包只过了本地假 STA 服务端的协议级自检
（live/selftest.py）。**istSOS4 本体未实测**；对其他 STA 实现的实测
（若有）也不等于 istSOS4 已验证。详见 docs/CALIBRATION.md。
"""
import io
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "istsos-consumer-bridge"
SERVER_VERSION = "0.1.0"

TOKEN_FILE = os.environ.get("ISTSOS_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".istsos-agent-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"), ".istsos-agent-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "calls.jsonl")

# ---- 防拉爆硬上限（改这些数字等于改本包的安全口径，须同步改文档与自检） ----
MAX_TOP = 100            # 单次请求 $top 上限
DEFAULT_TOP = 50         # 列表工具缺省 $top
MAX_PAGES = 3            # 列表跟随 @iot.nextLink 的页数上限
MAX_LIST_ITEMS = 300     # 列表返回条目总量上限
MAX_OBSERVATIONS = 100   # get_observations 条数上限
MAX_EXPORT = 500         # 导出观测条数上限
EXPORT_PAGE_TOP = 100    # 导出时每页 $top
MAX_EXPORT_PAGES = 5     # 导出跟随 nextLink 页数上限（100×5=500 与总量一致）
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 单次响应读取上限
HTTP_TIMEOUT_S = 10


def log(*a):
    print("[istsos-mcp]", *a, file=sys.stderr, flush=True)


# ---- 序列化净化（与 fme/arcmap 已修版同口径） ----
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
    tok = os.environ.get("ISTSOS_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def ensure_token():
    """env 与 token 文件都没有 token 时，生成随机 token 写入文件
    （与本合集应用内桥“启动生成随机 token”同口径）。返回生效 token。"""
    tok = expected_token()
    if tok:
        return tok
    tok = secrets.token_hex(16)
    try:
        d = os.path.dirname(TOKEN_FILE)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(tok + "\n")
    except Exception as e:
        log("token file write failed: %s" % e)
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


# ------------------------------------------------------------------ STA
class StaError(Exception):
    def __init__(self, error_code, message, http_status=None):
        Exception.__init__(self, message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status


def base_url():
    raw = (os.environ.get("ISTSOS_BASE_URL") or "").strip()
    return raw.rstrip("/") or None


def _sta_get(url):
    """唯一的网络出口：只发 GET。返回解析后的 JSON（dict）。"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent",
                   "gis-agent-bridges/%s/%s" % (SERVER_NAME, SERVER_VERSION))
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise StaError("STA_HTTP_ERROR",
                       "STA 服务端返回 HTTP %d: %s" % (e.code, e.reason),
                       http_status=e.code)
    except Exception as e:
        raise StaError("STA_UNREACHABLE", "连不上 STA 服务端: %s" % e)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise StaError("STA_RESPONSE_TOO_LARGE",
                       "单次响应超过 %d 字节上限，已中止读取"
                       % MAX_RESPONSE_BYTES)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise StaError("STA_BAD_RESPONSE", "响应不是合法 JSON: %s" % e)
    if not isinstance(data, dict):
        raise StaError("STA_BAD_RESPONSE", "响应顶层不是 JSON 对象")
    return data


def _entity_url(path, params=None):
    url = base_url() + "/" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def _fetch_collection(path, top, max_pages=MAX_PAGES, max_items=MAX_LIST_ITEMS):
    """取一个 STA 集合：首请带 $top，跟随 @iot.nextLink 但受硬上限约束。
    返回 (items, meta)。"""
    items = []
    url = _entity_url(path, {"$top": top})
    pages = 0
    truncated = False
    while url and pages < max_pages and len(items) < max_items:
        data = _sta_get(url)
        value = data.get("value")
        if not isinstance(value, list):
            raise StaError("STA_BAD_RESPONSE",
                           "集合响应缺少 value 数组: %s" % path)
        items.extend(value)
        pages += 1
        url = data.get("@iot.nextLink")
        if url and (pages >= max_pages or len(items) >= max_items):
            truncated = True
    if len(items) > max_items:
        items = items[:max_items]
        truncated = True
    return items, {"pages_fetched": pages, "truncated": truncated}


def _need_base():
    if base_url() is None:
        return {"ok": False, "error_code": "NOT_CONFIGURED",
                "message": "未配置 ISTSOS_BASE_URL，未发出任何请求；"
                           "请把 STA 服务端基地址写入该环境变量"
                           "（形如 http://localhost:8080/istsos4/v1.1，"
                           "占位示例、非真实服务）"}
    return None


def _validate_limit(value, default, hard_max, name):
    """返回 (limit, error_dict)。超上限直接拒绝，不静默截断。"""
    if value is None:
        return default, None
    try:
        n = int(value)
    except Exception:
        return None, {"ok": False, "error_code": "BAD_LIMIT",
                      "message": "%s 必须是整数" % name}
    if n < 1 or n > hard_max:
        return None, {"ok": False, "error_code": "LIMIT_EXCEEDED",
                      "message": "%s=%d 超出允许范围 1..%d，已拒绝"
                                 % (name, n, hard_max)}
    return n, None


def _validate_id(value, name):
    try:
        n = int(value)
    except Exception:
        return None, {"ok": False, "error_code": "BAD_ID",
                      "message": "%s 必须是正整数 id" % name}
    if n < 1:
        return None, {"ok": False, "error_code": "BAD_ID",
                      "message": "%s 必须是正整数 id" % name}
    return n, None


# ------------------------------------------------------------------ tools
def tool_ping(args):
    info = {"ok": True, "pong": True, "bridge": SERVER_NAME,
            "version": SERVER_VERSION, "mode": "consumer-readonly",
            "base_url_configured": base_url() is not None,
            "base_url": base_url()}
    err = _need_base()
    if err:
        info["server_reachable"] = False
        info["note"] = err["message"]
        return info
    try:
        data = _sta_get(base_url())
        names = [v.get("name") for v in data.get("value", [])
                 if isinstance(v, dict)]
        info["server_reachable"] = True
        info["sta_landing_entries"] = names
    except StaError as e:
        info["server_reachable"] = False
        info["error_code"] = e.error_code
        info["note"] = e.message
    return info


def tool_discover(args):
    return {"ok": True, "mode": "consumer-readonly",
            "server_name": SERVER_NAME, "version": SERVER_VERSION,
            "base_url": base_url(),
            "base_url_configured": base_url() is not None,
            "token_guard": bool(_ACTIVE_TOKEN or expected_token()),
            "limits": {"max_top": MAX_TOP, "default_top": DEFAULT_TOP,
                       "max_pages": MAX_PAGES,
                       "max_list_items": MAX_LIST_ITEMS,
                       "max_observations": MAX_OBSERVATIONS,
                       "max_export": MAX_EXPORT,
                       "max_response_bytes": MAX_RESPONSE_BYTES,
                       "http_timeout_s": HTTP_TIMEOUT_S},
            "output_dir": os.environ.get("ISTSOS_BRIDGE_OUTPUT_DIR")
                          or os.getcwd(),
            "http_methods_used": ["GET"],
            "write_tools": [],
            "calibration_note": "仅协议级自检（本地假 STA 服务端）；"
                                "istSOS4 本体未实测，见 docs/CALIBRATION.md"}


def tool_list_things(args):
    err = _need_base()
    if err:
        return err
    top, err = _validate_limit(args.get("top"), DEFAULT_TOP, MAX_TOP, "top")
    if err:
        return err
    try:
        items, meta = _fetch_collection("Things", top)
    except StaError as e:
        return {"ok": False, "error_code": e.error_code,
                "message": e.message, "http_status": e.http_status}
    things = [{"id": t.get("@iot.id"), "name": t.get("name"),
               "description": t.get("description")}
              for t in items if isinstance(t, dict)]
    return {"ok": True, "count": len(things), "things": things,
            "pages_fetched": meta["pages_fetched"],
            "truncated": meta["truncated"]}


def tool_list_datastreams(args):
    err = _need_base()
    if err:
        return err
    top, err = _validate_limit(args.get("top"), DEFAULT_TOP, MAX_TOP, "top")
    if err:
        return err
    path = "Datastreams"
    thing_id = args.get("thing_id")
    if thing_id is not None:
        thing_id, err = _validate_id(thing_id, "thing_id")
        if err:
            return err
        path = "Things(%d)/Datastreams" % thing_id
    try:
        items, meta = _fetch_collection(path, top)
    except StaError as e:
        return {"ok": False, "error_code": e.error_code,
                "message": e.message, "http_status": e.http_status}
    streams = []
    for d in items:
        if not isinstance(d, dict):
            continue
        unit = d.get("unitOfMeasurement") or {}
        streams.append({"id": d.get("@iot.id"), "name": d.get("name"),
                        "description": d.get("description"),
                        "unit_symbol": unit.get("symbol"),
                        "unit_name": unit.get("name")})
    return {"ok": True, "count": len(streams), "datastreams": streams,
            "pages_fetched": meta["pages_fetched"],
            "truncated": meta["truncated"]}


def _get_observations_page(ds_id, top, page_url=None):
    if page_url:
        return _sta_get(page_url)
    url = _entity_url("Datastreams(%d)/Observations" % ds_id,
                      {"$top": top, "$orderby": "phenomenonTime desc"})
    return _sta_get(url)


def _trim_observation(o):
    if not isinstance(o, dict):
        return {"raw": "%s" % (o,)}
    return {"id": o.get("@iot.id"),
            "phenomenonTime": o.get("phenomenonTime"),
            "result": o.get("result"),
            "resultTime": o.get("resultTime")}


def tool_get_observations(args):
    err = _need_base()
    if err:
        return err
    ds_id, err = _validate_id(args.get("datastream_id"), "datastream_id")
    if err:
        return err
    limit, err = _validate_limit(args.get("limit"), 20,
                                 MAX_OBSERVATIONS, "limit")
    if err:
        return err
    try:
        data = _get_observations_page(ds_id, limit)
    except StaError as e:
        return {"ok": False, "error_code": e.error_code,
                "message": e.message, "http_status": e.http_status}
    value = data.get("value")
    if not isinstance(value, list):
        return {"ok": False, "error_code": "STA_BAD_RESPONSE",
                "message": "Observations 响应缺少 value 数组"}
    obs = [_trim_observation(o) for o in value[:limit]]
    return {"ok": True, "datastream_id": ds_id, "count": len(obs),
            "observations": obs}


def _thing_id_of_datastream(ds_id):
    """取 Datastream 所属 Thing 的 id：优先 $expand=Thing，
    回退解析 Thing@iot.navigationLink 里的 (id)。"""
    data = _sta_get(_entity_url("Datastreams(%d)" % ds_id,
                                {"$expand": "Thing"}))
    thing = data.get("Thing")
    if isinstance(thing, dict) and thing.get("@iot.id") is not None:
        return int(thing["@iot.id"])
    link = data.get("Thing@iot.navigationLink") or ""
    m = re.search(r"Things\((\d+)\)", link)
    if m:
        return int(m.group(1))
    raise StaError("STA_BAD_RESPONSE",
                   "无法从 Datastream 响应确定所属 Thing id")


def _first_location_geometry(thing_id):
    items, _meta = _fetch_collection("Things(%d)/Locations" % thing_id,
                                     MAX_TOP, max_pages=1)
    for loc in items:
        if isinstance(loc, dict) and isinstance(loc.get("location"), dict):
            return loc["location"]
    return None


def tool_export_observations_geojson(args):
    err = _need_base()
    if err:
        return err
    ds_id, err = _validate_id(args.get("datastream_id"), "datastream_id")
    if err:
        return err
    limit, err = _validate_limit(args.get("limit"), 100, MAX_EXPORT, "limit")
    if err:
        return err
    out_dir = args.get("directory") or \
        os.environ.get("ISTSOS_BRIDGE_OUTPUT_DIR") or os.getcwd()
    try:
        thing_id = _thing_id_of_datastream(ds_id)
        geometry = _first_location_geometry(thing_id)
        if geometry is None:
            return {"ok": False, "error_code": "NO_LOCATION",
                    "message": "Thing %d 没有可用位置，未生成文件"
                               "（不伪造坐标）" % thing_id}
        observations = []
        url = None
        pages = 0
        while len(observations) < limit and pages < MAX_EXPORT_PAGES:
            data = _get_observations_page(ds_id, EXPORT_PAGE_TOP,
                                          page_url=url)
            value = data.get("value")
            if not isinstance(value, list):
                return {"ok": False, "error_code": "STA_BAD_RESPONSE",
                        "message": "Observations 响应缺少 value 数组"}
            observations.extend(value)
            pages += 1
            url = data.get("@iot.nextLink")
            if not url:
                break
        observations = observations[:limit]
    except StaError as e:
        return {"ok": False, "error_code": e.error_code,
                "message": e.message, "http_status": e.http_status}
    features = []
    for o in observations:
        if not isinstance(o, dict):
            continue
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "datastream_id": ds_id,
                "thing_id": thing_id,
                "observation_id": o.get("@iot.id"),
                "phenomenonTime": o.get("phenomenonTime"),
                "result": o.get("result"),
                "resultTime": o.get("resultTime"),
            }})
    collection = {"type": "FeatureCollection", "features": features,
                  "properties": {
                      "source": "OGC SensorThings API via %s %s"
                                % (SERVER_NAME, SERVER_VERSION),
                      "base_url": base_url(),
                      "datastream_id": ds_id,
                      "exported_at": datetime.now().isoformat(
                          timespec="seconds"),
                      "geometry_note": "geometry 取自该 Datastream 所属 "
                                       "Thing 的第一个 Location，"
                                       "全部观测共用该点位"}}
    try:
        os.makedirs(out_dir, exist_ok=True)
        fname = "observations_ds%d_%s.geojson" % (
            ds_id, datetime.now().strftime("%Y%m%d-%H%M%S"))
        fpath = os.path.join(out_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(collection, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"ok": False, "error_code": "EXPORT_WRITE_FAILED",
                "message": "写出 GeoJSON 失败: %s" % e}
    return {"ok": True, "path": fpath, "datastream_id": ds_id,
            "thing_id": thing_id, "features": len(features),
            "geometry_type": geometry.get("type")}


_STR = {"type": "string"}
_INT = {"type": "integer"}

TOOL_DEFS = [
    ("istsos_ping",
     "连通性检查：桥是否在线、STA 基地址是否已配置、服务端根路径是否可达",
     {}),
    ("istsos_discover",
     "环境发现：基地址、硬上限、token 守卫、导出目录与校准口径（校准用）",
     {}),
    ("istsos_list_things",
     "【只读】列出 STA 服务端的 Things（id、名称、描述）；top 为单页条数，"
     "上限 100，超限拒绝",
     {"top": dict(_INT, description="单页条数（可选，默认 50，范围 1..100）")}),
    ("istsos_list_datastreams",
     "【只读】列出 Datastreams（id、名称、单位符号）；传 thing_id 只看"
     "某个 Thing 的流；top 上限 100，超限拒绝",
     {"top": dict(_INT, description="单页条数（可选，默认 50，范围 1..100）"),
      "thing_id": dict(_INT, description="Thing id（可选，正整数）")}),
    ("istsos_get_observations",
     "【只读】取某个 Datastream 的观测（按 phenomenonTime 倒序）："
     "phenomenonTime、result、resultTime；limit 上限 100，超限拒绝",
     {"datastream_id": dict(_INT, description="Datastream id（必填，正整数）"),
      "limit": dict(_INT, description="条数（可选，默认 20，范围 1..100）")}),
    ("istsos_export_observations_geojson",
     "【只读远端·本地落文件】把某个 Datastream 的观测导出为 GeoJSON："
     "几何取所属 Thing 的第一个 Location，观测值进 properties；"
     "limit 上限 500，超限拒绝；无位置时报 NO_LOCATION 不伪造坐标",
     {"datastream_id": dict(_INT, description="Datastream id（必填，正整数）"),
      "limit": dict(_INT, description="条数（可选，默认 100，范围 1..500）"),
      "directory": dict(_STR, description="输出目录（可选，缺省用 "
                        "ISTSOS_BRIDGE_OUTPUT_DIR 或当前目录）")}),
]

HANDLERS = {
    "istsos_ping": tool_ping,
    "istsos_discover": tool_discover,
    "istsos_list_things": tool_list_things,
    "istsos_list_datastreams": tool_list_datastreams,
    "istsos_get_observations": tool_get_observations,
    "istsos_export_observations_geojson": tool_export_observations_geojson,
}


def tools_list():
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props in TOOL_DEFS]


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools_list()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = dict(params.get("arguments") or {})
        supplied = args.pop("_token", None)
        expect = _ACTIVE_TOKEN or expected_token()
        if expect and supplied != expect:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(
                    {"ok": False, "error_code": "BAD_TOKEN",
                     "message": "token 缺失或不正确"}, ensure_ascii=False)}],
                "isError": True}}
        handler = HANDLERS.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "unknown tool: %s" % name}],
                "isError": True}}
        try:
            result = handler(args)
            journal({"tool": name, "ok": bool(result.get("ok"))})
            text = json.dumps(_to_text(result), ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            journal({"tool": name, "ok": False, "error": str(e)})
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": "tool failed: %s" % e}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    global _ACTIVE_TOKEN
    _lock_stdio_utf8()
    _ACTIVE_TOKEN = ensure_token()
    log("starting; base_url=%s token_guard=on journal=%s" % (
        base_url() or "(not configured)", JOURNAL_FILE))
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
            sys.stdout.write(json.dumps(_to_text(resp), ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
