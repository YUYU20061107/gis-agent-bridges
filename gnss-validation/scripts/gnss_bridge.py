# -*- coding: utf-8 -*-
"""
gnss_bridge.py — GNSS×GIS 验证桥的解析 / 验证 / 纠偏库
（纯标准库，供 live/mcp_server.py 与 scripts/probe_api.py 共用）

定位：本桥不连任何 GNSS 设备、不实现差分/RTK，只对**已落盘的轨迹
文件**（NMEA 0183 日志、GPX）做离线验证与纠偏：拿本地 GIS 参考图层
（GeoJSON 线/面）逐点比对偏离、检测跳点与静止漂移、按 fix 类型与
HDOP 分层统计，并把纠偏结果写成**新的** GeoJSON 文件。它不提供
任意代码执行、任意路径访问或网络能力：

  * 一切输入/输出路径都必须是相对路径，解析后必须落在环境变量
    GNSS_WORK_DIR 指定的工作目录内（realpath 比对，挡 ..、绝对
    路径与符号链接逃逸）；工作目录未配置时文件类工具一律以
    NOT_CONFIGURED 拒绝，不猜默认目录；
  * 输出文件只许 .geojson、只许新文件：目标已存在即 OUTPUT_EXISTS
    拒绝，永不覆盖原件，轨迹原文件只读不写；
  * 轨迹点数硬上限 MAX_TRACK_POINTS=10000：读取类工具超限截断并
    在回报里明示 truncated，不静默丢点；
  * 距离口径如实标注：图层偏离用「以轨迹质心纬度为基准的等距
    圆柱（平面）近似」换算米制距离，短距离内足够，但不是测地线
    精确距离；点间距离（速度/修正量）用 haversine 球面距离。
    无参考图层时 accuracy 只能给轨迹自洽统计，绝不冒充精度真值。

NMEA 解析口径：定位点以 GGA 语句为主（fix quality / 卫星数 /
HDOP 都在 GGA 里）；日期取自 RMC 的日期字段（预扫首条 RMC 定
初始日期，主解析按各点前最近一条 RMC 滚动更新）与 GGA 的 UTC
时刻拼合；只有 RMC 没有 GGA 时退化为 RMC 点
（fix 记 "RMC"，HDOP/卫星数为空）。带 *XX 校验和的语句先验
校验和，不过的整句跳过并计数；fix quality=0 或坐标为空的
GGA 记为无定位行跳过并计数。GPX 解析取 trkpt 的 lat/lon 与
time/fix/sat/hdop 子元素（GPX 1.1 标准元素，缺失即为空）。

环境变量：
  GNSS_WORK_DIR   工作目录（必填；一切轨迹/图层/输出文件都在其内）
"""
import json
import math
import os
import xml.etree.ElementTree as ET

EARTH_R = 6371000.0          # 球面近似半径（米）
MAX_TRACK_POINTS = 10000     # 轨迹点数硬上限（改动须同步文档与自检）
DEFAULT_TRACK_LIMIT = 1000   # gnss_track_read 缺省返回点数
MAX_FILE_BYTES = 64 * 1024 * 1024   # 单个输入文件大小硬上限
MAX_OVER_LIST = 200          # 超限/可疑清单回报条数上限（总数另报）

FIX_LABELS = {
    0: "无定位", 1: "GPS", 2: "DGPS", 3: "PPS", 4: "RTK固定",
    5: "RTK浮动", 6: "估算", 7: "手动输入", 8: "模拟",
}


class BridgeError(Exception):
    """带结构化错误码的桥内错误；mcp_server 会原样转成工具错误回报。"""

    def __init__(self, error_code, message):
        Exception.__init__(self, message)
        self.error_code = error_code
        self.message = message


# ------------------------------------------------------------------ 配置
def work_dir():
    return os.environ.get("GNSS_WORK_DIR") or None


def require_work_dir():
    wd = work_dir()
    if not wd:
        raise BridgeError(
            "NOT_CONFIGURED",
            "GNSS_WORK_DIR 未配置：出于安全口径，文件类工具在没有显式"
            "工作目录时一律拒绝执行，不猜默认目录")
    if not os.path.isdir(wd):
        raise BridgeError(
            "WORK_DIR_MISSING",
            "GNSS_WORK_DIR 指向的目录不存在：%s" % wd)
    return os.path.realpath(wd)


# ------------------------------------------------------------------ 路径
def resolve_in_path(rel):
    """输入路径：必须相对、解析后必须落在工作目录内。返回绝对路径。"""
    base = require_work_dir()
    if not isinstance(rel, str) or not rel.strip():
        raise BridgeError("BAD_PATH", "path 必填（工作目录内的相对路径）")
    if os.path.isabs(rel):
        raise BridgeError(
            "PATH_OUTSIDE_WORKDIR",
            "只接受工作目录内的相对路径，不接受绝对路径：%r" % (rel,))
    full = os.path.realpath(os.path.join(base, rel))
    if os.path.commonpath([base, full]) != base:
        raise BridgeError(
            "PATH_OUTSIDE_WORKDIR",
            "路径解析后不在 GNSS_WORK_DIR 内：%r" % (rel,))
    if not os.path.isfile(full):
        raise BridgeError("FILE_NOT_FOUND", "文件不存在：%r" % (rel,))
    if os.path.getsize(full) > MAX_FILE_BYTES:
        raise BridgeError(
            "FILE_TOO_LARGE",
            "文件超过大小硬上限 %d 字节：%r" % (MAX_FILE_BYTES, rel))
    return full


def resolve_out_path(rel):
    """输出路径：相对、.geojson、落在工作目录内、且必须尚不存在。"""
    base = require_work_dir()
    if not isinstance(rel, str) or not rel.strip():
        raise BridgeError("BAD_PATH", "output 必填（工作目录内的相对路径）")
    if os.path.isabs(rel):
        raise BridgeError(
            "PATH_OUTSIDE_WORKDIR",
            "只接受工作目录内的相对路径，不接受绝对路径：%r" % (rel,))
    if not rel.lower().endswith(".geojson"):
        raise BridgeError(
            "BAD_FILENAME", "output 必须以 .geojson 结尾：%r" % (rel,))
    full = os.path.realpath(os.path.join(base, rel))
    if os.path.commonpath([base, full]) != base:
        raise BridgeError(
            "PATH_OUTSIDE_WORKDIR",
            "输出路径解析后不在 GNSS_WORK_DIR 内：%r" % (rel,))
    if os.path.exists(full):
        raise BridgeError(
            "OUTPUT_EXISTS",
            "输出文件已存在，拒绝覆盖（纠偏只产新文件）：%r" % (rel,))
    return full


def write_new_geojson(full_path, data):
    parent = os.path.dirname(full_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # 二次确认不存在，防止与校验之间的竞态覆盖
    if os.path.exists(full_path):
        raise BridgeError("OUTPUT_EXISTS",
                          "输出文件已存在，拒绝覆盖：%s" % full_path)
    with open(full_path, "x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return os.path.getsize(full_path)


# ------------------------------------------------------------------ 数值
def haversine_m(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * \
        math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def median(vals):
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def mean(vals):
    return (sum(vals) / len(vals)) if vals else None


def rms(vals):
    if not vals:
        return None
    return math.sqrt(sum(v * v for v in vals) / len(vals))


def dist_stats(vals):
    """一组距离的分布摘要（空集全 None，不编造）。"""
    if not vals:
        return {"count": 0, "min_m": None, "median_m": None,
                "mean_m": None, "rms_m": None, "max_m": None}
    return {"count": len(vals),
            "min_m": round(min(vals), 3),
            "median_m": round(median(vals), 3),
            "mean_m": round(mean(vals), 3),
            "rms_m": round(rms(vals), 3),
            "max_m": round(max(vals), 3)}


# ------------------------------------------------------------------ NMEA
def _nmea_checksum_ok(line):
    """校验 *XX 校验和；无校验和字段的语句视为不可信，跳过。"""
    if "*" not in line:
        return False
    body, _star, tail = line[1:].partition("*")
    if len(tail) < 2:
        return False
    try:
        expect = int(tail[:2], 16)
    except Exception:
        return False
    got = 0
    for ch in body:
        got ^= ord(ch)
    return got == expect


def _parse_latlon(lat_s, lat_h, lon_s, lon_h):
    if not lat_s or not lon_s:
        return None, None
    try:
        lat_deg = int(lat_s[:2])
        lat_min = float(lat_s[2:])
        lon_deg = int(lon_s[:3])
        lon_min = float(lon_s[3:])
    except Exception:
        return None, None
    lat = lat_deg + lat_min / 60.0
    lon = lon_deg + lon_min / 60.0
    if lat_h == "S":
        lat = -lat
    if lon_h == "W":
        lon = -lon
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None
    return lat, lon


def _hms_to_seconds(hms):
    try:
        h = int(hms[0:2])
        m = int(hms[2:4])
        s = float(hms[4:])
    except Exception:
        return None
    return h * 3600 + m * 60 + s


def _date_to_days(ddmmyy):
    """RMC 日期 ddmmyy -> 自 2000-01-01 起的天数（仅作相对时间轴）。"""
    try:
        d = int(ddmmyy[0:2])
        mo = int(ddmmyy[2:4])
        y = 2000 + int(ddmmyy[4:6])
    except Exception:
        return None
    # Howard Hinnant days_from_civil，相对 1970-01-01
    yy = y - (1 if mo <= 2 else 0)
    era = (yy if yy >= 0 else yy - 399) // 400
    yoe = yy - era * 400
    mp = (mo + 9) % 12
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _iso_from_epoch_days(days, seconds):
    if days is None or seconds is None:
        return None
    import datetime
    try:
        dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(
            days=days, seconds=seconds)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def parse_nmea(text):
    """解析 NMEA 文本 -> (points, info)。

    points 元素：{seq, t_epoch(秒,相对轴), time_iso, lat, lon,
                  fix(标签), fix_code, sats, hdop, source}
    t_epoch 仅在日期与时刻都齐时给出（供速度类计算）；否则 None。
    """
    points = []
    info = {"sentences": 0, "bad_checksum": 0, "no_fix_lines": 0,
            "unparsed_lines": 0}
    # 预扫一遍取首条 RMC 的日期作初始值：不少记录仪是先 GGA 后 RMC
    # 交错输出，首点 GGA 出现时还没有任何 RMC，只靠「最近一条」会
    # 让首点丢日期。跨日轨迹仍由主循环里 last_days 的滚动更新处理。
    last_days = None
    for raw0 in text.splitlines():
        line0 = raw0.strip()
        if line0.startswith("$") and _nmea_checksum_ok(line0):
            f0 = line0[1:].split("*")[0].split(",")
            if len(f0) >= 10 and f0[0][-3:] == "RMC":
                last_days = _date_to_days(f0[9])
                if last_days is not None:
                    break
    rmc_points = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("$"):
            if line:
                info["unparsed_lines"] += 1
            continue
        info["sentences"] += 1
        if not _nmea_checksum_ok(line):
            info["bad_checksum"] += 1
            continue
        body = line[1:].split("*")[0]
        fields = body.split(",")
        kind = fields[0][-3:] if len(fields[0]) >= 3 else ""
        if kind == "RMC" and len(fields) >= 10:
            days = _date_to_days(fields[9])
            if days is not None:
                last_days = days
            if fields[2] == "A":
                lat, lon = _parse_latlon(fields[3], fields[4],
                                         fields[5], fields[6])
                if lat is not None:
                    secs = _hms_to_seconds(fields[1])
                    rmc_points.append({
                        "lat": lat, "lon": lon,
                        "t_epoch": (last_days * 86400 + secs)
                        if (last_days is not None and secs is not None)
                        else None,
                        "time_iso": _iso_from_epoch_days(last_days, secs),
                    })
            continue
        if kind != "GGA" or len(fields) < 10:
            continue
        try:
            quality = int(fields[6]) if fields[6] else 0
        except Exception:
            quality = 0
        lat, lon = _parse_latlon(fields[2], fields[3],
                                 fields[4], fields[5])
        if quality == 0 or lat is None:
            info["no_fix_lines"] += 1
            continue
        secs = _hms_to_seconds(fields[1])
        try:
            sats = int(fields[7]) if fields[7] else None
        except Exception:
            sats = None
        try:
            hdop = float(fields[8]) if fields[8] else None
        except Exception:
            hdop = None
        points.append({
            "lat": lat, "lon": lon,
            "t_epoch": (last_days * 86400 + secs)
            if (last_days is not None and secs is not None) else None,
            "time_iso": _iso_from_epoch_days(last_days, secs),
            "fix": FIX_LABELS.get(quality, "fix%d" % quality),
            "fix_code": quality, "sats": sats, "hdop": hdop,
            "source": "GGA",
        })
    if not points and rmc_points:
        for rp in rmc_points:
            points.append({
                "lat": rp["lat"], "lon": rp["lon"],
                "t_epoch": rp["t_epoch"], "time_iso": rp["time_iso"],
                "fix": "RMC", "fix_code": None, "sats": None,
                "hdop": None, "source": "RMC",
            })
        info["fallback_rmc"] = True
    for i, p in enumerate(points):
        p["seq"] = i
    return points, info


# ------------------------------------------------------------------ GPX
def parse_gpx(text):
    try:
        root = ET.fromstring(text)
    except Exception as e:
        raise BridgeError("BAD_GPX", "GPX 解析失败：%s" % e)
    points = []
    import datetime
    for el in root.iter():
        if not el.tag.endswith("trkpt"):
            continue
        try:
            lat = float(el.get("lat"))
            lon = float(el.get("lon"))
        except Exception:
            continue
        rec = {"lat": lat, "lon": lon, "t_epoch": None, "time_iso": None,
               "fix": None, "fix_code": None, "sats": None, "hdop": None,
               "source": "GPX"}
        for child in el:
            tag = child.tag.split("}")[-1]
            if tag == "time" and child.text:
                rec["time_iso"] = child.text.strip()
                try:
                    dt = datetime.datetime.fromisoformat(
                        rec["time_iso"].replace("Z", "+00:00"))
                    rec["t_epoch"] = dt.timestamp()
                except Exception:
                    pass
            elif tag == "fix" and child.text:
                rec["fix"] = child.text.strip()
            elif tag == "sat" and child.text:
                try:
                    rec["sats"] = int(child.text.strip())
                except Exception:
                    pass
            elif tag == "hdop" and child.text:
                try:
                    rec["hdop"] = float(child.text.strip())
                except Exception:
                    pass
        if rec["fix"] is None:
            rec["fix"] = "GPX"
        points.append(rec)
    for i, p in enumerate(points):
        p["seq"] = i
    return points, {"trkpt": len(points)}


# ------------------------------------------------------------------ 装载
def load_track(rel_path):
    """按扩展名装载轨迹 -> (points, meta)。points 是全量解析结果。"""
    full = resolve_in_path(rel_path)
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    ext = os.path.splitext(full)[1].lower()
    if ext == ".gpx":
        points, info = parse_gpx(text)
        fmt = "GPX"
    elif ext in (".nmea", ".log", ".txt"):
        points, info = parse_nmea(text)
        fmt = "NMEA"
    else:
        raise BridgeError(
            "BAD_FORMAT",
            "只支持 .nmea/.log/.txt（NMEA）与 .gpx 轨迹文件：%r"
            % (rel_path,))
    if not points:
        raise BridgeError(
            "NO_POINTS",
            "文件中没有解析出任何定位点（无定位行 %s、坏校验和 %s）"
            % (info.get("no_fix_lines"), info.get("bad_checksum")))
    return points, {"format": fmt, "parse_info": info, "path": rel_path}


def cap_points(points, limit):
    """按硬上限截断 -> (kept, truncated)。limit 先钳到 1..MAX。"""
    lim = max(1, min(int(limit), MAX_TRACK_POINTS))
    if len(points) > lim:
        return points[:lim], True
    return points, False


def summarize_points(points):
    fixes = {}
    sats = []
    hdops = []
    for p in points:
        fixes[p["fix"]] = fixes.get(p["fix"], 0) + 1
        if p.get("sats") is not None:
            sats.append(p["sats"])
        if p.get("hdop") is not None:
            hdops.append(p["hdop"])
    timed = [p for p in points if p.get("t_epoch") is not None]
    span = None
    if len(timed) >= 2:
        span = round(max(p["t_epoch"] for p in timed)
                     - min(p["t_epoch"] for p in timed), 3)
    return {
        "points": len(points),
        "fix_counts": fixes,
        "sats": ({"min": min(sats), "max": max(sats),
                  "mean": round(mean(sats), 2)} if sats else None),
        "hdop": ({"min": min(hdops), "max": max(hdops),
                  "mean": round(mean(hdops), 3)} if hdops else None),
        "first_time": timed[0]["time_iso"] if timed else None,
        "last_time": timed[-1]["time_iso"] if timed else None,
        "time_span_s": span,
    }


# ------------------------------------------------------------------ 图层
class LocalPlane:
    """以参考纬度为基准的等距圆柱（平面）近似：经纬度 -> 本地米制 XY。"""

    def __init__(self, lat0):
        self.lat0 = lat0
        self.kx = EARTH_R * math.cos(math.radians(lat0)) * math.pi / 180.0
        self.ky = EARTH_R * math.pi / 180.0

    def xy(self, lat, lon):
        return (lon * self.kx, lat * self.ky)

    def latlon(self, x, y):
        return (y / self.ky, x / self.kx)


def _iter_geometries(obj):
    """GeoJSON 对象 -> 几何对象流（展开 Feature/Collection）。"""
    if not isinstance(obj, dict):
        return
    t = obj.get("type")
    if t == "FeatureCollection":
        for f in obj.get("features") or []:
            for g in _iter_geometries(f):
                yield g
    elif t == "Feature":
        for g in _iter_geometries(obj.get("geometry")):
            yield g
    elif t == "GeometryCollection":
        for g in obj.get("geometries") or []:
            for gg in _iter_geometries(g):
                yield gg
    elif t in ("Point", "MultiPoint", "LineString", "MultiLineString",
               "Polygon", "MultiPolygon"):
        yield obj


def load_layer(rel_path):
    """装载参考图层 GeoJSON -> (segments, polygons, points, plane, meta)。

    segments: [((x1,y1),(x2,y2)), ...]；polygons: [[(x,y),...], ...]
    （外环与内环一并作边、内部判定只用外环另存 outer_rings）；
    points: [(x,y), ...]。平面基准纬度取图层坐标均值纬度。
    """
    full = resolve_in_path(rel_path)
    with open(full, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            raise BridgeError("BAD_GEOJSON", "参考图层不是合法 JSON：%s" % e)
    raw_geoms = list(_iter_geometries(data))
    if not raw_geoms:
        raise BridgeError("EMPTY_LAYER", "参考图层里没有任何几何对象")
    lats = []

    def _collect(coords):
        if isinstance(coords, (list, tuple)) and coords and \
                isinstance(coords[0], (int, float)):
            lats.append(coords[1])
        elif isinstance(coords, (list, tuple)):
            for c in coords:
                _collect(c)

    for g in raw_geoms:
        _collect(g.get("coordinates"))
    plane = LocalPlane(mean(lats) if lats else 0.0)
    segments = []
    outer_rings = []
    points_xy = []

    def ring_segments(ring):
        pts = [plane.xy(c[1], c[0]) for c in ring]
        for i in range(len(pts) - 1):
            segments.append((pts[i], pts[i + 1]))
        return pts

    for g in raw_geoms:
        t = g["type"]
        c = g.get("coordinates")
        if t == "Point":
            points_xy.append(plane.xy(c[1], c[0]))
        elif t == "MultiPoint":
            for p in c:
                points_xy.append(plane.xy(p[1], p[0]))
        elif t == "LineString":
            ring_segments(c)
        elif t == "MultiLineString":
            for line in c:
                ring_segments(line)
        elif t == "Polygon":
            for ri, ring in enumerate(c):
                pts = ring_segments(ring)
                if ri == 0:
                    outer_rings.append(pts)
        elif t == "MultiPolygon":
            for poly in c:
                for ri, ring in enumerate(poly):
                    pts = ring_segments(ring)
                    if ri == 0:
                        outer_rings.append(pts)
    return {"segments": segments, "outer_rings": outer_rings,
            "points": points_xy, "plane": plane,
            "geometry_count": len(raw_geoms)}


def _point_seg_dist(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    ll = dx * dx + dy * dy
    if ll == 0:
        return math.hypot(px - ax, py - ay), (ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.hypot(px - qx, py - qy), (qx, qy)


def _inside_ring(px, py, ring):
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > py) != (y2 > py):
            xin = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xin:
                inside = not inside
    return inside


def distance_to_layer(lat, lon, layer):
    """点到图层的最短距离（米，平面近似）-> (dist, nearest_xy 或 None)。"""
    plane = layer["plane"]
    px, py = plane.xy(lat, lon)
    for ring in layer["outer_rings"]:
        if _inside_ring(px, py, ring):
            return 0.0, (px, py)
    best = None
    best_q = None
    for (ax, ay), (bx, by) in layer["segments"]:
        d, q = _point_seg_dist(px, py, ax, ay, bx, by)
        if best is None or d < best:
            best = d
            best_q = q
    for qx, qy in layer["points"]:
        d = math.hypot(px - qx, py - qy)
        if best is None or d < best:
            best = d
            best_q = (qx, qy)
    return best, best_q


DIST_METHOD_NOTE = (
    "平面近似：以参考图层平均纬度为基准的等距圆柱投影换算米制距离，"
    "短距离（公里级以内）适用，不是测地线精确距离；每点距离可由原始"
    "坐标按同一口径复算")


# ------------------------------------------------------------------ 检测
def detect_anomalies(points, max_speed_mps=60.0, max_accel_mps2=15.0,
                     drift_radius_m=5.0, drift_min_seconds=30.0,
                     drift_rms_m=2.0):
    """速度/加速度异常与静止漂移检测 -> (findings, notes)。

    findings 元素：{seq, kind, reason, ...数值}。kind 取值：
    speed（段速超限，seq 为该段终点）、accel（速度变化率超限，
    seq 为中间点之后的第一点）、drift（一整段静止漂移，seq 为段首、
    附 seq_end 与窗口统计）。
    """
    findings = []
    notes = []
    timed = [p for p in points if p.get("t_epoch") is not None]
    if len(timed) < 2:
        notes.append("轨迹缺少可用时间戳，速度/加速度/漂移检测全部跳过")
        return findings, notes
    speeds = []  # (end_seq, v, dt)
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        if a.get("t_epoch") is None or b.get("t_epoch") is None:
            continue
        dt = b["t_epoch"] - a["t_epoch"]
        if dt <= 0:
            continue
        d = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
        v = d / dt
        speeds.append((b["seq"], v, dt))
        if v > max_speed_mps:
            findings.append({
                "seq": b["seq"], "kind": "speed",
                "reason": "段速 %.2f m/s 超过阈值 %.2f m/s（%.2f m / %.1f s）"
                          % (v, max_speed_mps, d, dt),
                "speed_mps": round(v, 3), "segment_m": round(d, 3),
                "dt_s": dt})
    for i in range(1, len(speeds)):
        (s0, v0, _d0), (s1, v1, dt1) = speeds[i - 1], speeds[i]
        acc = abs(v1 - v0) / dt1 if dt1 > 0 else 0.0
        if acc > max_accel_mps2:
            findings.append({
                "seq": s1, "kind": "accel",
                "reason": "速度由 %.2f 突变为 %.2f m/s，变化率 %.2f m/s² "
                          "超过阈值 %.2f" % (v0, v1, acc, max_accel_mps2),
                "accel_mps2": round(acc, 3),
                "from_speed_mps": round(v0, 3), "to_speed_mps": round(v1, 3)})
    # 静止漂移：从每点起找「净位移始终 < drift_radius」的最大窗口，
    # 窗口时长达标且窗口内对质心的 RMS 散布超限 -> 漂移。
    n = len(points)
    i = 0
    while i < n:
        p0 = points[i]
        if p0.get("t_epoch") is None:
            i += 1
            continue
        j = i
        while j + 1 < n:
            q = points[j + 1]
            if q.get("t_epoch") is None:
                break
            if haversine_m(p0["lat"], p0["lon"],
                           q["lat"], q["lon"]) >= drift_radius_m:
                break
            j += 1
        if j > i:
            dur = points[j]["t_epoch"] - p0["t_epoch"]
            if dur >= drift_min_seconds:
                window = points[i:j + 1]
                clat = mean([p["lat"] for p in window])
                clon = mean([p["lon"] for p in window])
                spread = rms([haversine_m(clat, clon, p["lat"], p["lon"])
                              for p in window])
                if spread is not None and spread > drift_rms_m:
                    findings.append({
                        "seq": p0["seq"], "seq_end": points[j]["seq"],
                        "kind": "drift",
                        "reason": "静止窗口 %.0f s 内净位移 < %.1f m，但对"
                                  "质心 RMS 散布 %.2f m 超过 %.2f m："
                                  "疑似静止漂移" % (dur, drift_radius_m,
                                                    spread, drift_rms_m),
                        "duration_s": dur,
                        "spread_rms_m": round(spread, 3),
                        "window_points": len(window)})
                    i = j + 1
                    continue
        i += 1
    return findings, notes


# ------------------------------------------------------------------ 纠偏
def track_feature_collection(points, corrected, corrections, summary):
    """纠偏结果 FeatureCollection：每点一个 Point Feature，带原始
    坐标与修正量；corrected 为与 points 等长的 (lat, lon) 列表。"""
    feats = []
    for p, (clat, clon), corr in zip(points, corrected, corrections):
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [clon, clat]},
            "properties": {
                "seq": p["seq"], "time": p.get("time_iso"),
                "fix": p.get("fix"), "hdop": p.get("hdop"),
                "orig_lat": p["lat"], "orig_lon": p["lon"],
                "correction_m": corr,
            },
        })
    return {"type": "FeatureCollection", "features": feats,
            "correction_summary": summary}


def smooth_points(points, window):
    """居中滑动平均（窗口内均值，边缘收缩窗口）-> (corrected, corr_m)。"""
    if not isinstance(window, int) or window < 3 or window % 2 == 0:
        raise BridgeError(
            "BAD_ARGUMENT", "window 必须是 ≥3 的奇数，收到 %r" % (window,))
    half = window // 2
    corrected = []
    corrs = []
    n = len(points)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        seg = points[lo:hi]
        clat = mean([p["lat"] for p in seg])
        clon = mean([p["lon"] for p in seg])
        corrected.append((clat, clon))
        corrs.append(round(haversine_m(points[i]["lat"], points[i]["lon"],
                                       clat, clon), 3))
    return corrected, corrs


def offset_from_pairs(pairs):
    """配对 -> (平均偏移 east_m, north_m, 每对偏移列表)。

    偏移定义：真值点相对观测点的位移（把观测纠到真值需要移动的量）。
    以各对纬度均值为基准做平面换算，口径随回报给出。
    """
    if not isinstance(pairs, list) or not pairs:
        raise BridgeError("BAD_ARGUMENT", "pairs 必须是非空数组")
    offs = []
    for k, pr in enumerate(pairs):
        try:
            olat = float(pr["observed_lat"])
            olon = float(pr["observed_lon"])
            tlat = float(pr["truth_lat"])
            tlon = float(pr["truth_lon"])
        except Exception:
            raise BridgeError(
                "BAD_ARGUMENT",
                "pairs[%d] 须含 observed_lat/observed_lon/truth_lat/"
                "truth_lon 四个数值" % k)
        plane = LocalPlane((olat + tlat) / 2.0)
        ox, oy = plane.xy(olat, olon)
        tx, ty = plane.xy(tlat, tlon)
        offs.append({"index": k, "east_m": round(tx - ox, 3),
                     "north_m": round(ty - oy, 3)})
    east = mean([o["east_m"] for o in offs])
    north = mean([o["north_m"] for o in offs])
    return east, north, offs


def snap_points(points, layer):
    """逐点吸附到图层最近点 -> (corrected, corrections_m)。

    corrected 为与 points 等长的 (lat, lon) 列表；图层为空集时
    原样返回、修正量 0。距离与最近点都走 distance_to_layer 的
    平面近似口径。
    """
    plane = layer["plane"]
    corrected = []
    corrs = []
    for p in points:
        d, q = distance_to_layer(p["lat"], p["lon"], layer)
        if q is None or d is None:
            corrected.append((p["lat"], p["lon"]))
            corrs.append(0.0)
            continue
        clat, clon = plane.latlon(q[0], q[1])
        corrected.append((clat, clon))
        corrs.append(round(d, 3))
    return corrected, corrs


def apply_offset(points, east_m, north_m):
    """整轨按平均偏移（东/北，米）平移 -> (corrected, corrections_m)。

    平面基准纬度取轨迹纬度均值；每点修正量恒为偏移模长。
    """
    lat0 = mean([p["lat"] for p in points])
    plane = LocalPlane(lat0)
    mag = round(math.hypot(east_m, north_m), 3)
    corrected = []
    corrs = []
    for p in points:
        x, y = plane.xy(p["lat"], p["lon"])
        corrected.append(plane.latlon(x + east_m, y + north_m))
        corrs.append(mag)
    return corrected, corrs


def _hdop_band(hdop):
    if hdop is None:
        return "未知"
    if hdop <= 1.0:
        return "≤1"
    if hdop <= 2.0:
        return "1-2"
    if hdop <= 5.0:
        return "2-5"
    return ">5"


def accuracy_by_bands(points, deviations, with_layer):
    """分层偏离统计 -> {basis, note, overall, by_fix, by_hdop}。

    with_layer=True 时 deviations 是与 points 等长的逐点到图层
    距离；False 时退化为自洽量：内点到其前后点连线中点的距离
    （抖动量级），端点不计——自洽统计不是精度真值，note 里明示。
    """
    if with_layer:
        measures = list(deviations)
        aligned = list(points)
        basis = "reference-layer-deviation"
        note = ("偏离 = 逐点到参考图层的最短距离（平面近似口径）；"
                "参考图层自身的误差会进入统计，本结果是相对该图层"
                "的偏离分布，不是大地测量级精度鉴定")
    else:
        measures = []
        aligned = []
        for i in range(1, len(points) - 1):
            a, b = points[i - 1], points[i + 1]
            mlat = (a["lat"] + b["lat"]) / 2.0
            mlon = (a["lon"] + b["lon"]) / 2.0
            measures.append(haversine_m(points[i]["lat"],
                                        points[i]["lon"], mlat, mlon))
            aligned.append(points[i])
        basis = "self-consistency"
        note = ("无参考图层：自洽统计不是精度真值——这里量的是内点"
                "到前后点连线中点的偏离（抖动/噪声量级，端点不计），"
                "系统性偏移与恒定偏差它看不见；要谈精度必须给 "
                "layer 或用控制点配对")
    by_fix = {}
    by_hdop = {}
    for p, m in zip(aligned, measures):
        by_fix.setdefault(p.get("fix") or "未知", []).append(m)
        by_hdop.setdefault(_hdop_band(p.get("hdop")), []).append(m)
    return {
        "basis": basis,
        "note": note,
        "overall": dist_stats(measures),
        "by_fix": {k: dist_stats(v) for k, v in sorted(by_fix.items())},
        "by_hdop": {k: dist_stats(v) for k, v in by_hdop.items()},
    }
