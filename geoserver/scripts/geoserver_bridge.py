# -*- coding: utf-8 -*-
"""
geoserver_bridge.py — GeoServer 消费侧只读桥的 HTTP / 校验库
（纯标准库，供 live/mcp_server.py 与 scripts/probe_api.py 共用）

定位：本库是消费侧工具箱——地图服务由你自己的 GeoServer 提供，
本库只以只读方式取它的 REST 目录（工作区、图层、图层详情）与
OGC GetCapabilities 摘要。它不提供任何写操作，也不提供任意
URL 抓取能力：

  * 对 GeoServer 只发 GET 请求；没有任何创建/修改/删除图层、
    工作区或数据的工具；
  * 服务端基地址只从环境变量 GEOSERVER_BASE_URL 读（应指向
    GeoServer 的 web 应用根，形如 http://localhost:8080/geoserver，
    占位示例、非真实服务），代码里不写死任何真实服务地址；
    未配置时业务工具返回 NOT_CONFIGURED；
  * 请求路径只由固定模板拼装：/rest/workspaces.json、
    /rest/layers.json、/rest/layers/<name>.json 与
    WMS/WFS GetCapabilities；工作区名、图层名等路径段先经
    字符集校验再 URL 编码，不接受调用方提供的完整 URL；
  * 图层详情里跟随的 resource href 是服务端返回的数据，按
    不可信输入处理：只有与基地址同源（scheme＋host＋port 一致）
    才跟随，否则只回报不请求（防 SSRF 跳板）；
  * 防拉爆硬上限：单次响应读取 ≤ 2 MiB、请求超时 10 秒、列表
    返回 ≤ 300 条（GeoServer REST 列表无服务端分页，桥在本地
    截断并如实标注 truncated=true，不假装给全）；
  * 可选 Basic 认证只从 GEOSERVER_USER / GEOSERVER_PASSWORD
    环境变量读，密码不进日志、不进回报；discover 只报是否已
    配置认证，不报值。

环境变量：
  GEOSERVER_BASE_URL     GeoServer 基地址（必填）
  GEOSERVER_USER         REST 认证用户名（可选）
  GEOSERVER_PASSWORD     REST 认证密码（可选，只供请求头使用）
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

MAX_LIST_ITEMS = 300         # 列表返回条目上限（本地截断并标注）
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
    raw = (os.environ.get("GEOSERVER_BASE_URL") or "").strip()
    return raw.rstrip("/") or None


def auth_configured():
    return bool(os.environ.get("GEOSERVER_USER"))


def _auth_header():
    user = os.environ.get("GEOSERVER_USER") or ""
    if not user:
        return None
    password = os.environ.get("GEOSERVER_PASSWORD") or ""
    raw = ("%s:%s" % (user, password)).encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


# ------------------------------------------------------------------ 校验
def validate_segment(value, field):
    """工作区/存储/图层名单段：字符集锁死后才进 URL 路径。"""
    if not isinstance(value, str) or not NAME_RE.match(value or ""):
        raise BridgeError(
            "BAD_NAME",
            "%s 非法：只允许 [A-Za-z0-9_.-]，收到 %r" % (field, value))
    if value in (".", ".."):
        raise BridgeError("BAD_NAME", "%s 不许是 %r" % (field, value))
    return value


def validate_layer_name(value):
    """图层名：'name' 或 'workspace:name'，两段各自过字符集校验。"""
    if not isinstance(value, str) or not value:
        raise BridgeError("BAD_NAME", "图层名必填，收到 %r" % (value,))
    parts = value.split(":")
    if len(parts) > 2:
        raise BridgeError("BAD_NAME", "图层名最多含一个冒号：%r" % (value,))
    for p in parts:
        validate_segment(p, "图层名")
    return value


def same_origin(url):
    """href 跟随守卫：只许与基地址同 scheme＋host＋port。"""
    base = base_url()
    if not base or not url:
        return False
    b = urllib.parse.urlparse(base)
    u = urllib.parse.urlparse(url)
    return (b.scheme, b.hostname, b.port) == (u.scheme, u.hostname, u.port)


# ------------------------------------------------------------------ HTTP
def http_get(url, accept="application/json"):
    """唯一的网络出口：只发 GET，带响应大小与超时硬上限。
    返回 (content_type, raw_bytes)。"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", accept)
    req.add_header("User-Agent", "gis-agent-bridges/geoserver-consumer-bridge")
    auth = _auth_header()
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
            ctype = resp.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as e:
        raise BridgeError("HTTP_ERROR",
                          "GeoServer 返回 HTTP %d: %s" % (e.code, e.reason),
                          http_status=e.code)
    except Exception as e:
        raise BridgeError("UNREACHABLE", "连不上 GeoServer: %s" % e)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise BridgeError("RESPONSE_TOO_LARGE",
                          "单次响应超过 %d 字节上限，已中止读取"
                          % MAX_RESPONSE_BYTES)
    return ctype, raw


def rest_url(path):
    return base_url() + "/rest/" + path


def get_json(path):
    _ctype, raw = http_get(rest_url(path))
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise BridgeError("BAD_RESPONSE", "响应不是合法 JSON: %s" % e)
    if not isinstance(data, dict):
        raise BridgeError("BAD_RESPONSE", "响应顶层不是 JSON 对象")
    return data


# ------------------------------------------------------------- 结果整形
def parse_workspaces(data):
    node = (data.get("workspaces") or {}).get("workspace") or []
    if isinstance(node, dict):
        node = [node]
    out = []
    for w in node:
        if isinstance(w, dict):
            out.append({"name": w.get("name")})
    return out


def parse_layers(data):
    node = (data.get("layers") or {}).get("layer") or []
    if isinstance(node, dict):
        node = [node]
    out = []
    for layer in node:
        if isinstance(layer, dict):
            out.append({"name": layer.get("name"),
                        "type": layer.get("type")})
    return out


def cap_list(items):
    """REST 列表无服务端分页：本地截到硬上限并如实标注 truncated。"""
    if len(items) > MAX_LIST_ITEMS:
        return items[:MAX_LIST_ITEMS], True
    return items, False


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_child(elem, local_name):
    for child in elem:
        if _local(child.tag) == local_name:
            return child
    return None


def _find_path(elem, names):
    cur = elem
    for name in names:
        if cur is None:
            return None
        cur = _find_child(cur, name)
    return cur


def parse_capabilities(raw, service):
    """解析 WMS/WFS GetCapabilities XML，取服务标题与图层/要素名。
    只做摘要，不回传整份 XML。"""
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        raise BridgeError("BAD_XML", "GetCapabilities 不是合法 XML: %s" % e)
    result = {"root_element": _local(root.tag)}
    if service == "wms":
        title_el = _find_path(root, ["Service", "Title"])
        result["service_title"] = title_el.text if title_el is not None else None
        cap_layer = _find_path(root, ["Capability", "Layer"])
        names = []
        if cap_layer is not None:
            for layer in cap_layer.iter():
                if _local(layer.tag) == "Layer":
                    name_el = _find_child(layer, "Name")
                    if name_el is not None and name_el.text:
                        names.append(name_el.text)
        result["layers"] = names
        result["layer_count"] = len(names)
    else:  # wfs
        title_el = _find_path(root, ["ServiceIdentification", "Title"])
        result["service_title"] = title_el.text if title_el is not None else None
        names = []
        ft_list = _find_child(root, "FeatureTypeList")
        if ft_list is not None:
            for ft in ft_list:
                if _local(ft.tag) == "FeatureType":
                    name_el = _find_child(ft, "Name")
                    if name_el is not None and name_el.text:
                        names.append(name_el.text)
        result["feature_types"] = names
        result["feature_type_count"] = len(names)
    return result
