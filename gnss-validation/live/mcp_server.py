# -*- coding: utf-8 -*-
"""
mcp_server.py — GNSS×GIS 验证桥 MCP 服务端（stdio，纯标准库）

启动：python3 live/mcp_server.py
配置只读环境变量 GNSS_WORK_DIR：轨迹日志（NMEA/GPX）与参考
图层（GeoJSON）都只能是该目录内的相对路径（防穿越）；三个
纠偏工具只往该目录写新 .geojson 文件、永不覆盖已有文件。
不需要 GNSS 设备；实时串口/NTRIP 流是 v0.2，未做（见 LIVE.md）。

token 校验（与仓内消费侧桥同口径）：
  环境变量 GNSS_BRIDGE_TOKEN 优先；否则 ~/.gnss-validation-bridge.token；
  都没有时启动即生成一个随机 token 写进该文件（权限 0600 并打到
  stderr）。每次 tools/call 都必须在参数里带 _token 且全等，
  否则拒绝（BAD_TOKEN）。记账：每次 tools/call 往
  ~/.gnss-validation-bridge/runs.jsonl 追加一行（工具名、输入文件
  名、状态、耗时；不含 token、不含坐标）。

工具（8 个，全部离线）：
  gnss_status                  NMEA 日志汇总（fix/卫星/HDOP/时间）
  gnss_track_read              读 NMEA/GPX 轨迹点列（硬上限明示截断）
  gnss_validate_against_layer  逐点到参考图层的最短距离与超限清单
  gnss_detect_jumps            跳点/瞬移/静止漂移检测
  gnss_accuracy_report         按 fix/HDOP 分层的偏离统计（无图层
                               退化为自洽统计并明示不是精度真值）
  gnss_correct_snap            吸附纠偏（confirm，只写新文件）
  gnss_correct_smooth          平滑纠偏（confirm，只写新文件）
  gnss_correct_offset          控制点偏移校正（confirm；配对<2 只报
                               偏移不产文件）
距离口径：等距圆柱平面近似（图层纬度均值定尺度），见
scripts/gnss_bridge.py 的 DIST_METHOD_NOTE；结论只用于离线筛查。
"""
import json
import os
import secrets
import sys
import time

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "gnss-validation-bridge"
VERSION = "0.1.0"

TOKEN_FILE = os.path.join(os.path.expanduser("~"),
                          ".gnss-validation-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"),
                           ".gnss-validation-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "runs.jsonl")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))

import gnss_bridge as nb  # noqa: E402


def log(*a):
    print("[gnss-mcp]", *a, file=sys.stderr, flush=True)


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


for _name in ("stdout", "stdin"):
    _stream = getattr(sys, _name, None)
    _buf = getattr(_stream, "buffer", None)
    if _buf is None or getattr(_stream, "encoding", None) == "utf-8":
        continue
    try:
        setattr(sys, _name, open(_buf.fileno(), mode=_stream.mode,
                                 encoding="utf-8", errors="replace",
                                 closefd=False))
    except Exception:
        pass


def expected_token():
    tok = os.environ.get("GNSS_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def ensure_token_file():
    if expected_token():
        return
    tok = secrets.token_urlsafe(24)
    try:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tok)
        log("已生成本地 token 文件（0600）：%s" % TOKEN_FILE)
        log("新 token：%s —— 填进 MCP 客户端配置 env 的 "
            "GNSS_BRIDGE_TOKEN 即完成配对。" % tok)
    except Exception as e:
        log("生成 token 文件失败：%r —— 可改用环境变量 "
            "GNSS_BRIDGE_TOKEN" % (e,))


def journal(record):
    try:
        if not os.path.isdir(JOURNAL_DIR):
            os.makedirs(JOURNAL_DIR)
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(_to_text(record), ensure_ascii=False) + "\n")
    except Exception:
        pass


def _bridge_error(e):
    return {"ok": False, "error_code": e.error_code, "message": e.message}


def _run_tool(name, args):
    t0 = time.time()
    try:
        result = _dispatch(name, args)
        status = result.get("error_code") or "OK"
    except nb.BridgeError as e:
        status = e.error_code
        record = _bridge_error(e)
        record["elapsed_ms"] = int((time.time() - t0) * 1000)
        return record
    if isinstance(result, dict):
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
    journal({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "tool": name, "status": status,
             "track": args.get("path"), "layer": args.get("layer")})
    return result


def _require_confirm(args, what):
    if args.get("confirm") is not True:
        raise nb.BridgeError(
            "CONFIRM_REQUIRED",
            "%s 是文件写操作，须在参数中显式传 confirm=true 才会执行"
            "（只写新文件、永不覆盖已有文件）" % what)


def _num_arg(args, key, default, lo, hi):
    v = args.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise nb.BridgeError("BAD_ARGUMENT", "%s 必须是数值，收到 %r"
                             % (key, v))
    if not (lo <= v <= hi):
        raise nb.BridgeError(
            "BAD_ARGUMENT", "%s=%r 超出允许范围 [%s, %s]" % (key, v, lo, hi))
    return v


def _load_track_arg(args):
    path = args.get("path")
    if not path or not isinstance(path, _TEXT):
        raise nb.BridgeError("BAD_ARGUMENT",
                             "path 必填：工作目录内的轨迹相对路径")
    return nb.load_track(path)


# ---- 各工具实现 ----

def _tool_status(args):
    points, meta = _load_track_arg(args)
    out = {"ok": True, "path": args.get("path"), "format": meta["format"]}
    out.update(nb.summarize_points(points))
    if meta.get("parse_info") is not None:
        out["parse_info"] = meta["parse_info"]
    return out


def _tool_track_read(args):
    points, meta = _load_track_arg(args)
    raw = args.get("limit", nb.DEFAULT_TRACK_LIMIT)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise nb.BridgeError("BAD_ARGUMENT",
                             "limit 必须是 ≥1 的整数，收到 %r" % (raw,))
    eff = min(raw, nb.MAX_TRACK_POINTS)
    total = len(points)
    shown = points[:eff]
    return {"ok": True, "path": args.get("path"), "format": meta["format"],
            "total_points": total, "returned_points": len(shown),
            "truncated": len(shown) < total,
            "points": shown,
            "note": ("返回点数硬上限 %d：limit 超过上限按上限截断，"
                     "truncated=true 明示被截断；文件解析点数见 "
                     "total_points" % nb.MAX_TRACK_POINTS)}


def _tool_validate(args):
    points, _meta = _load_track_arg(args)
    layer_name = args.get("layer")
    if not layer_name or not isinstance(layer_name, _TEXT):
        raise nb.BridgeError("BAD_ARGUMENT",
                             "layer 必填：工作目录内的 GeoJSON 相对路径")
    layer = nb.load_layer(layer_name)
    threshold = _num_arg(args, "threshold_m", 10.0, 0.0, 100000.0)
    deviations = []
    over = []
    for p in points:
        d, q = nb.distance_to_layer(p["lat"], p["lon"], layer)
        deviations.append(d)
        if d > threshold:
            nlat, nlon = layer["plane"].latlon(q[0], q[1])
            over.append({"seq": p["seq"], "time_utc": p.get("time_iso"),
                         "lat": p["lat"], "lon": p["lon"],
                         "distance_m": round(d, 3),
                         "nearest_lon": round(nlon, 7),
                         "nearest_lat": round(nlat, 7)})
    if len(over) > nb.MAX_OVER_LIST:
        over_shown, over_trunc = over[:nb.MAX_OVER_LIST], True
    else:
        over_shown, over_trunc = over, False
    return {"ok": True, "path": args.get("path"), "layer": layer_name,
            "layer_geometry": {"segments": len(layer["segments"]),
                               "rings": len(layer["outer_rings"]),
                               "points": len(layer["points"])},
            "threshold_m": threshold,
            "deviation": nb.dist_stats(deviations),
            "over_threshold_count": len(over),
            "over_threshold": over_shown,
            "over_threshold_truncated": over_trunc,
            "distance_method": nb.DIST_METHOD_NOTE}


def _tool_detect(args):
    points, _meta = _load_track_arg(args)
    max_speed = _num_arg(args, "max_speed_mps", 60.0, 0.1, 1000.0)
    max_accel = _num_arg(args, "max_accel_mps2", 15.0, 0.1, 1000.0)
    drift_radius = _num_arg(args, "drift_radius_m", 5.0, 0.1, 1000.0)
    drift_min_s = _num_arg(args, "drift_min_seconds", 30.0, 1.0, 86400.0)
    drift_rms = _num_arg(args, "drift_rms_m", 2.0, 0.1, 1000.0)
    findings, notes = nb.detect_anomalies(
        points, max_speed_mps=max_speed, max_accel_mps2=max_accel,
        drift_radius_m=drift_radius, drift_min_seconds=drift_min_s,
        drift_rms_m=drift_rms)
    return {"ok": True, "path": args.get("path"), "points": len(points),
            "thresholds": {"max_speed_mps": max_speed,
                           "max_accel_mps2": max_accel,
                           "drift_radius_m": drift_radius,
                           "drift_min_seconds": drift_min_s,
                           "drift_rms_m": drift_rms},
            "suspicious_count": len(findings),
            "suspicious": findings,
            "notes": notes,
            "distance_method": nb.DIST_METHOD_NOTE}


def _tool_accuracy(args):
    points, _meta = _load_track_arg(args)
    out = {"ok": True, "path": args.get("path")}
    layer_name = args.get("layer")
    if layer_name:
        layer = nb.load_layer(layer_name)
        dists = [nb.distance_to_layer(p["lat"], p["lon"], layer)[0]
                 for p in points]
        out.update(nb.accuracy_by_bands(points, dists, with_layer=True))
        out["layer"] = layer_name
    else:
        out.update(nb.accuracy_by_bands(points, None, with_layer=False))
    out["distance_method"] = nb.DIST_METHOD_NOTE
    return out


def _write_corrected(args, kind, points, corrected, corrections,
                     pair_info=None):
    max_c = round(max(corrections), 3) if corrections else 0.0
    mean_c = round(sum(corrections) / len(corrections), 3) \
        if corrections else 0.0
    summary = {"kind": kind, "points": len(corrected),
               "max_correction_m": max_c, "mean_correction_m": mean_c,
               "distance_method": nb.DIST_METHOD_NOTE}
    fc = nb.track_feature_collection(points, corrected, corrections,
                                     summary)
    full = nb.resolve_out_path(args.get("output"))
    size = nb.write_new_geojson(full, fc)
    out = {"ok": True, "kind": kind, "points": len(corrected),
           "output": args.get("output"), "written": True, "bytes": size,
           "max_correction_m": max_c, "mean_correction_m": mean_c}
    if pair_info:
        out.update(pair_info)
    return out


def _tool_correct_snap(args):
    _require_confirm(args, "gnss_correct_snap")
    points, _meta = _load_track_arg(args)
    layer_name = args.get("layer")
    if not layer_name or not isinstance(layer_name, _TEXT):
        raise nb.BridgeError("BAD_ARGUMENT",
                             "layer 必填：工作目录内的 GeoJSON 相对路径")
    layer = nb.load_layer(layer_name)
    corrected, corrections = nb.snap_points(points, layer)
    out = _write_corrected(args, "snap", points, corrected, corrections)
    out["layer"] = layer_name
    out["distance_method"] = nb.DIST_METHOD_NOTE
    return out


def _tool_correct_smooth(args):
    _require_confirm(args, "gnss_correct_smooth")
    points, _meta = _load_track_arg(args)
    window = args.get("window", 5)
    if isinstance(window, bool) or not isinstance(window, int):
        raise nb.BridgeError("BAD_ARGUMENT",
                             "window 必须是整数（≥3 的奇数），收到 %r"
                             % (window,))
    corrected, corrections = nb.smooth_points(points, window)
    out = _write_corrected(args, "smooth", points, corrected, corrections)
    out["window"] = window
    out["distance_method"] = nb.DIST_METHOD_NOTE
    return out


def _tool_correct_offset(args):
    pairs = args.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise nb.BridgeError(
            "BAD_ARGUMENT",
            "pairs 必填且至少 1 个：每项含 observed_lat/observed_lon/"
            "truth_lat/truth_lon 四个数值")
    east, north, per_pair = nb.offset_from_pairs(pairs)
    mag = (east ** 2 + north ** 2) ** 0.5
    info = {"mean_offset": {"east_m": round(east, 3),
                            "north_m": round(north, 3),
                            "magnitude_m": round(mag, 3)},
            "pairs": per_pair}
    if len(pairs) < 2:
        info["corrected"] = False
        info["written"] = False
        info["note"] = ("只给了 1 个配对：单点偏移混有该点自身的定位"
                        "误差，不能代表整条轨迹的系统偏移——按口径只报"
                        "偏移量、不产纠偏文件。补到 ≥2 个配对（最好分"
                        "布在轨迹两端）再纠偏")
        return dict({"ok": True, "kind": "offset"}, **info)
    _require_confirm(args, "gnss_correct_offset")
    points, _meta = _load_track_arg(args)
    corrected, corrections = nb.apply_offset(points, east, north)
    out = _write_corrected(args, "offset", points, corrected,
                           corrections, info)
    out["corrected"] = True
    out["distance_method"] = nb.DIST_METHOD_NOTE
    return out


_DISPATCH = {
    "gnss_status": _tool_status,
    "gnss_track_read": _tool_track_read,
    "gnss_validate_against_layer": _tool_validate,
    "gnss_detect_jumps": _tool_detect,
    "gnss_accuracy_report": _tool_accuracy,
    "gnss_correct_snap": _tool_correct_snap,
    "gnss_correct_smooth": _tool_correct_smooth,
    "gnss_correct_offset": _tool_correct_offset,
}


def _dispatch(name, args):
    fn = _DISPATCH.get(name)
    if fn is None:
        raise nb.BridgeError("NOT_IMPLEMENTED", "未知工具：%s" % name)
    return fn(args)


# ---- 工具表 ----

_PATH_PROP = {"type": "string",
              "description": "工作目录（GNSS_WORK_DIR）内的轨迹相对路径，"
                             "仅 .nmea/.log/.txt（NMEA）或 .gpx"}
_LAYER_PROP = {"type": "string",
               "description": "工作目录内的参考图层 GeoJSON 相对路径"
                              "（线/面要素，坐标为 WGS84 经纬度）"}
_OUTPUT_PROP = {"type": "string",
                "description": "输出文件名：工作目录内的新 .geojson "
                               "相对路径；文件已存在会被拒绝，永不覆盖"}
_CONFIRM_PROP = {"type": "boolean",
                 "description": "写文件确认：必须显式传 true 才执行"}

TOOLS = [
    {"name": "gnss_status",
     "description": "汇总一个 NMEA 轨迹日志：点数、fix 类型分布、"
                    "卫星数与 HDOP 范围、起止时间与跨度、解析计数"
                    "（坏校验和/无定位语句数）。只读本地文件。",
     "inputSchema": {"type": "object",
                     "properties": {"path": _PATH_PROP},
                     "required": ["path"]}},
    {"name": "gnss_track_read",
     "description": "读取 NMEA 或 GPX 轨迹为结构化点列（序号、UTC "
                    "时间、经纬度、fix、卫星数、HDOP）。点数硬上限 "
                    "10000，超限截断并以 truncated 明示；limit 控制"
                    "本次返回条数。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "path": _PATH_PROP,
                         "limit": {"type": "integer", "minimum": 1,
                                   "maximum": 10000,
                                   "description": "返回点数上限，默认 1000"}},
                     "required": ["path"]}},
    {"name": "gnss_validate_against_layer",
     "description": "轨迹逐点到参考图层（本地 GeoJSON 线/面）的最短"
                    "距离：输出偏离分布统计与超过 threshold_m（默认 "
                    "10 m）的超限点清单（含最近点坐标，可独立复算）。"
                    "距离为等距圆柱平面近似，见返回的 distance_method。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "path": _PATH_PROP,
                         "layer": _LAYER_PROP,
                         "threshold_m": {"type": "number", "minimum": 0,
                                         "description": "超限阈值（米），"
                                                        "默认 10"}},
                     "required": ["path", "layer"]}},
    {"name": "gnss_detect_jumps",
     "description": "跳点/瞬移/静止漂移检测：段速超过 max_speed_mps"
                    "（默认 60）、加速度超过 max_accel_mps2（默认 15）、"
                    "以及长时间（默认 ≥30 s）困在小半径（默认 5 m）内"
                    "却持续抖动（质心 RMS>默认 2 m）的静止漂移段；输出"
                    "可疑点清单、理由与数值。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "path": _PATH_PROP,
                         "max_speed_mps": {"type": "number",
                                           "description": "段速阈值 m/s，默认 60"},
                         "max_accel_mps2": {"type": "number",
                                            "description": "加速度阈值 m/s²，默认 15"},
                         "drift_radius_m": {"type": "number",
                                            "description": "漂移判定半径 m，默认 5"},
                         "drift_min_seconds": {"type": "number",
                                               "description": "漂移最短持续 s，默认 30"},
                         "drift_rms_m": {"type": "number",
                                         "description": "漂移抖动 RMS 阈值 m，默认 2"}},
                     "required": ["path"]}},
    {"name": "gnss_accuracy_report",
     "description": "按 fix 类型与 HDOP 段分层的偏离统计（点数、中位"
                    "数、均方根 RMS）。给 layer 时基于逐点到图层的距离"
                    "（basis=reference-layer-deviation）；不给 layer 时"
                    "退化为轨迹自洽统计（相邻段速离散度，"
                    "basis=self-consistency）——自洽统计不是精度真值，"
                    "系统性偏移它看不见，结论里会明示。",
     "inputSchema": {"type": "object",
                     "properties": {"path": _PATH_PROP,
                                    "layer": _LAYER_PROP},
                     "required": ["path"]}},
    {"name": "gnss_correct_snap",
     "description": "【写】地图匹配纠偏：把轨迹逐点吸附到参考线/面"
                    "图层的最近点，写出新 GeoJSON（每点保留原始坐标"
                    "与修正量）。须 confirm=true；只写新文件、永不"
                    "覆盖；面图层内点（距离 0）保持原样。",
     "inputSchema": {"type": "object",
                     "properties": {"path": _PATH_PROP,
                                    "layer": _LAYER_PROP,
                                    "output": _OUTPUT_PROP,
                                    "confirm": _CONFIRM_PROP},
                     "required": ["path", "layer", "output"]}},
    {"name": "gnss_correct_smooth",
     "description": "【写】平滑纠偏：对轨迹坐标做居中滑动平均（窗口 "
                    "window，≥3 的奇数，默认 5），写出新 GeoJSON"
                    "（每点保留原始坐标与修正量）。须 confirm=true；"
                    "只写新文件、永不覆盖。平滑只压随机抖动，不修"
                    "系统偏移。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "path": _PATH_PROP,
                         "window": {"type": "integer", "minimum": 3,
                                    "description": "滑动窗口点数（奇数），默认 5"},
                         "output": _OUTPUT_PROP,
                         "confirm": _CONFIRM_PROP},
                     "required": ["path", "output"]}},
    {"name": "gnss_correct_offset",
     "description": "【写】控制点偏移校正：给 ≥2 个「轨迹观测点↔"
                    "真值点」配对，算平均偏移（东/北分量）后整轨平移，"
                    "写出新 GeoJSON。须 confirm=true；只写新文件、永不"
                    "覆盖。只给 1 个配对时只报偏移量、不产纠偏文件"
                    "（单点偏移混有该点自身误差，不能代表系统偏移）。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "path": _PATH_PROP,
                         "pairs": {"type": "array", "minItems": 1,
                                   "items": {"type": "object",
                                             "properties": {
                                                 "observed_lat": {"type": "number"},
                                                 "observed_lon": {"type": "number"},
                                                 "truth_lat": {"type": "number"},
                                                 "truth_lon": {"type": "number"}},
                                             "required": ["observed_lat",
                                                          "observed_lon",
                                                          "truth_lat",
                                                          "truth_lon"]},
                                   "description": "观测↔真值配对数组"},
                         "output": _OUTPUT_PROP,
                         "confirm": _CONFIRM_PROP},
                     "required": ["path", "pairs"]}},
]

# ---- JSON-RPC 主循环（stdio） ----

def handle(request):
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        return {"protocolVersion":
                params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": VERSION}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        token = args.pop("_token", None)
        exp = expected_token()
        if not exp or token != exp:
            record = {"ok": False, "error_code": "BAD_TOKEN",
                      "message": "缺少或错误的 _token：与服务端 "
                                 "GNSS_BRIDGE_TOKEN 环境变量或 "
                                 "~/.gnss-validation-bridge.token 文件"
                                 "内容比对不一致"}
            journal({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "tool": name, "status": "BAD_TOKEN"})
            return {"content": [{"type": "text",
                                 "text": json.dumps(_to_text(record),
                                                    ensure_ascii=False)}],
                    "isError": True}
        result = _run_tool(name, args)
        is_error = isinstance(result, dict) and \
            result.get("ok") is False
        return {"content": [{"type": "text",
                             "text": json.dumps(_to_text(result),
                                                ensure_ascii=False)}],
                "isError": bool(is_error)}
    raise RuntimeError("METHOD_NOT_FOUND: %s" % method)


def main():
    ensure_token_file()
    log("%s %s 已启动（stdio）。工作目录 GNSS_WORK_DIR=%s"
        % (SERVER_NAME, VERSION, nb.work_dir() or "(未配置)"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            request = json.loads(line)
            rid = request.get("id")
            if "id" not in request:
                continue  # 通知，无需响应
            result = handle(request)
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        except RuntimeError as e:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": str(e)}}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": "%r" % (e,)}}
        sys.stdout.write(json.dumps(_to_text(resp),
                                    ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
