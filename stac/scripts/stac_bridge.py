# -*- coding: utf-8 -*-
"""
stac_bridge.py — STAC 消费侧只读桥的 HTTP / 校验库
（纯标准库，供 live/mcp_server.py 与 scripts/probe_api.py 共用）

定位：本库是消费侧工具箱——遥感影像目录由 STAC API 服务端
（如 Microsoft Planetary Computer、Earth Search、Copernicus
Data Space 等公开目录，或自建的 stac-fastapi）提供，本库只以
只读方式检索目录：有哪些集合（collections）、某集合的时空
范围与许可、按集合/范围/条数查影像条目（items），并可把检索
结果导出成 GeoJSON 文件。它不下载影像数据本体，不提供任意
URL 抓取能力：

  * 对 STAC 服务端只发 GET 请求（/search 用 GET 形态，不用
    POST）；没有任何写工具；不跟随条目里的资产（assets）
    链接去下载数据——资产只回报键名清单，下载请用你自己的
    工具按集合许可进行；
  * 服务端基地址只从环境变量 STAC_BASE_URL 读（STAC API 的
    根地址，形如 https://example.org/stac，末尾不要带 /；
    占位示例、非真实服务），代码里不写死任何真实服务地址；
    未配置时业务工具返回 NOT_CONFIGURED；
  * 请求路径只由固定模板拼装：落地页、/collections、
    /collections/<id>、/search；集合 id 先经字符集校验再
    URL 编码；集合列表的 next 链接按不可信输入处理，只有
    与基地址同源才跟随（防 SSRF 跳板）；
  * 检索参数收窄：bbox 只许四个数且经纬度范围与顺序校验；
    limit 超硬上限直接以 LIMIT_EXCEEDED 拒绝，不静默截断；
  * 防拉爆硬上限：单次响应读取 ≤ 2 MiB、请求超时 10 秒、
    集合列表 ≤ 3 页且总量 ≤ 300 条、单次检索 ≤ 100 条、
    导出 ≤ 500 条。

环境变量：
  STAC_BASE_URL     STAC API 根地址（必填）
  STAC_API_KEY      可选：目标目录要求 API Key 时，经
                    Authorization: Bearer 头发送；只供请求头，
                    不进日志、不进回报，discover 只报是否配置
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

MAX_PAGES = 3                # 集合列表跟随 next 链接的页数上限
MAX_LIST_ITEMS = 300         # 集合列表返回条目总量上限
MAX_SEARCH = 100             # 单次检索条目硬上限
DEFAULT_SEARCH = 20          # 检索缺省条数
MAX_EXPORT = 500             # 导出条目硬上限
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 单次响应读取上限
HTTP_TIMEOUT_S = 10


class BridgeError(Exception):
    """带结构化错误码的桥内错误；mcp_server 会原样转成工具错误回报。"""

    def __init__(self, error_code, message, http_status=None):
        Exception.__init__(self, message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status


# ------------------------------------------------------------------ 配置
def base_url():
    raw = (os.environ.get("STAC_BASE_URL") or "").strip()
    return raw.rstrip("/") or None


def api_key_configured():
    return bool(os.environ.get("STAC_API_KEY"))


def same_origin(url):
    """next 链接跟随守卫：只许与基地址同 scheme＋host＋port。"""
    base = base_url()
    if not base or not url:
        return False
    b = urllib.parse.urlparse(base)
    u = urllib.parse.urlparse(url)
    return (b.scheme, b.hostname, b.port) == (u.scheme, u.hostname, u.port)


# ------------------------------------------------------------------ 校验
def validate_collection_id(value):
    if not isinstance(value, str) or not ID_RE.match(value or ""):
        raise BridgeError(
            "BAD_COLLECTION_ID",
            "集合 id 非法：只允许 [A-Za-z0-9_.-]，收到 %r" % (value,))
    if value in (".", ".."):
        raise BridgeError("BAD_COLLECTION_ID", "集合 id 不许是 %r" % (value,))
    return value


def validate_limit(value, default, hard_max, name="limit"):
    """条数上限：强转 int，超硬上限直接拒绝，不静默截断。"""
    if value is None:
        return default
    if isinstance(value, bool):
        raise BridgeError("BAD_LIMIT", "%s 必须是整数" % name)
    if isinstance(value, str) and re.match(r"^\d+$", value.strip()):
        value = int(value.strip())
    if not isinstance(value, int):
        raise BridgeError("BAD_LIMIT", "%s 必须是整数，收到 %r"
                          % (name, value))
    if value < 1 or value > hard_max:
        raise BridgeError(
            "LIMIT_EXCEEDED",
            "%s=%d 超出允许范围 1..%d，已拒绝" % (name, value, hard_max))
    return value


def validate_bbox(value):
    """bbox 只许 [minlon, minlat, maxlon, maxlat] 四个数，
    经纬度范围与 min<max 顺序都在本地校验，非法在发请求前拒绝。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise BridgeError(
            "BAD_BBOX", "bbox 必须是 [minlon, minlat, maxlon, maxlat] "
                        "四个数，收到 %r" % (value,))
    nums = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise BridgeError("BAD_BBOX", "bbox 元素必须是数：%r" % (v,))
        nums.append(float(v))
    minlon, minlat, maxlon, maxlat = nums
    if not (-180.0 <= minlon <= 180.0 and -180.0 <= maxlon <= 180.0):
        raise BridgeError("BAD_BBOX", "bbox 经度须在 -180..180 内")
    if not (-90.0 <= minlat <= 90.0 and -90.0 <= maxlat <= 90.0):
        raise BridgeError("BAD_BBOX", "bbox 纬度须在 -90..90 内")
    if not (minlon < maxlon and minlat < maxlat):
        raise BridgeError("BAD_BBOX", "bbox 须满足 min<max（经度与纬度）")
    return nums


# ------------------------------------------------------------------ HTTP
def http_get(url):
    """唯一的网络出口：只发 GET。返回解析后的 JSON（dict）。"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "gis-agent-bridges/stac-consumer-bridge")
    key = os.environ.get("STAC_API_KEY") or ""
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise BridgeError("HTTP_ERROR",
                          "STAC 服务端返回 HTTP %d: %s" % (e.code, e.reason),
                          http_status=e.code)
    except Exception as e:
        raise BridgeError("UNREACHABLE", "连不上 STAC 服务端: %s" % e)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise BridgeError("RESPONSE_TOO_LARGE",
                          "单次响应超过 %d 字节上限，已中止读取"
                          % MAX_RESPONSE_BYTES)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise BridgeError("BAD_RESPONSE", "响应不是合法 JSON: %s" % e)
    if not isinstance(data, dict):
        raise BridgeError("BAD_RESPONSE", "响应顶层不是 JSON 对象")
    return data


def api_url(path, params=None):
    url = base_url() + "/" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


# ------------------------------------------------------------- 结果整形
def trim_collection(c):
    """集合摘要：只留 id、标题、许可、时空范围与提供方名，
    描述截断到 300 字，不回传整份集合文档。"""
    if not isinstance(c, dict):
        return {"raw": "%s" % (c,)}
    extent = c.get("extent") or {}
    spatial = (extent.get("spatial") or {}).get("bbox") or []
    temporal = (extent.get("temporal") or {}).get("interval") or []
    providers = [p.get("name") for p in (c.get("providers") or [])
                 if isinstance(p, dict)]
    desc = c.get("description")
    return {"id": c.get("id"), "title": c.get("title"),
            "description": (desc[:300] if isinstance(desc, str) else desc),
            "license": c.get("license"),
            "spatial_bbox": spatial[0] if spatial else None,
            "temporal_interval": temporal[0] if temporal else None,
            "providers": providers}


def trim_item(item):
    """条目摘要：id、时间、云量等常用属性、资产键名与几何，
    不回传资产 href 的完整清单之外的多余字段。"""
    if not isinstance(item, dict):
        return {"raw": "%s" % (item,)}
    props = item.get("properties") or {}
    assets = item.get("assets") or {}
    return {"id": item.get("id"),
            "datetime": props.get("datetime"),
            "cloud_cover": props.get("eo:cloud_cover"),
            "platform": props.get("platform"),
            "instruments": props.get("instruments"),
            "collection": item.get("collection"),
            "assets": sorted(assets.keys()),
            "geometry": item.get("geometry")}


def fetch_collections():
    """取集合列表：首请 /collections，跟随 rel=next 链接但受硬
    上限约束（同源才跟随）。返回 (collections, meta)。"""
    items = []
    url = api_url("collections")
    pages = 0
    truncated = False
    while url and pages < MAX_PAGES and len(items) < MAX_LIST_ITEMS:
        data = http_get(url)
        value = data.get("collections")
        if not isinstance(value, list):
            raise BridgeError("BAD_RESPONSE",
                              "集合响应缺少 collections 数组")
        items.extend(value)
        pages += 1
        url = None
        for link in data.get("links") or []:
            if isinstance(link, dict) and link.get("rel") == "next" \
                    and link.get("href"):
                url = link["href"] if same_origin(link["href"]) else None
                if url is None:
                    truncated = True
                break
        if url and (pages >= MAX_PAGES or len(items) >= MAX_LIST_ITEMS):
            truncated = True
    if len(items) > MAX_LIST_ITEMS:
        items = items[:MAX_LIST_ITEMS]
        truncated = True
    return items, {"pages_fetched": pages, "truncated": truncated}


def search_items(collection_id, limit, bbox=None):
    """GET /search 检索：固定参数形态，只许 collections/limit/bbox。"""
    params = {"collections": collection_id, "limit": limit}
    if bbox is not None:
        params["bbox"] = ",".join("%s" % v for v in bbox)
    data = http_get(api_url("search", params))
    features = data.get("features")
    if not isinstance(features, list):
        raise BridgeError("BAD_RESPONSE", "检索响应缺少 features 数组")
    return features
