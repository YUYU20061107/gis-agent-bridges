# -*- coding: utf-8 -*-
"""
probe_api.py — istSOS 消费侧只读桥连通探针（纯标准库，只读）

在把基地址交给 MCP 服务端之前，先用这个脚本独立探一次目标 STA
服务端，结果留档。探针与 live/mcp_server.py 同口径：基地址只从环境
变量 ISTSOS_BASE_URL 读，代码不带任何默认端点；只发 GET；超时
10 秒、单次响应读取上限 2 MiB；计数请求只取 $top=1 并优先读
服务端返回的 @iot.count。

依次探：服务端根（落地页条目名）→ Things 计数 → Datastreams 计数。
任何一步失败都如实记进对应字段，不中断后续探针。未配置
ISTSOS_BASE_URL 时输出结构化 NOT_CONFIGURED 并以退出码 1 结束，
不发出任何请求。

用法：ISTSOS_BASE_URL=<STA 基地址> python3 scripts/probe_api.py
退出码：0 = 服务端根可达且是合法 STA 落地页；1 = 未配置/不可达。
注意：探通只证明 STA 协议级互通；目标是 FROST 等其他实现时，
不等于 istSOS4 已验证（校准口径见 docs/CALIBRATION.md）。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROBE_NAME = "istsos-consumer-bridge"
PROBE_VERSION = "0.1.0"
HTTP_TIMEOUT_S = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _get_json(url):
    """唯一的网络出口：只发 GET。成功返回 dict；失败抛 ProbeError。"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent",
                   "gis-agent-bridges/%s-probe/%s"
                   % (PROBE_NAME, PROBE_VERSION))
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise ProbeError("STA_HTTP_ERROR",
                         "服务端返回 HTTP %d: %s" % (e.code, e.reason))
    except Exception as e:
        raise ProbeError("STA_UNREACHABLE", "连不上服务端: %s" % e)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProbeError("STA_RESPONSE_TOO_LARGE",
                         "单次响应超过 %d 字节上限" % MAX_RESPONSE_BYTES)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ProbeError("STA_BAD_RESPONSE", "响应不是合法 JSON: %s" % e)
    if not isinstance(data, dict):
        raise ProbeError("STA_BAD_RESPONSE", "响应顶层不是 JSON 对象")
    return data


class ProbeError(Exception):
    def __init__(self, error_code, message):
        Exception.__init__(self, message)
        self.error_code = error_code
        self.message = message


def _count(base, collection):
    """取集合计数：$top=1&$count=true，优先 @iot.count（精确），
    没有时退回首頁条数并标注 count_exact=false。"""
    url = base + "/" + collection + "?" + urllib.parse.urlencode(
        {"$top": 1, "$count": "true"})
    try:
        data = _get_json(url)
    except ProbeError as e:
        return {"ok": False, "error_code": e.error_code,
                "message": e.message}
    value = data.get("value")
    if not isinstance(value, list):
        return {"ok": False, "error_code": "STA_BAD_RESPONSE",
                "message": "集合响应缺少 value 数组"}
    count = data.get("@iot.count")
    if isinstance(count, int):
        return {"ok": True, "count": count, "count_exact": True}
    return {"ok": True, "count": len(value), "count_exact": False,
            "note": "服务端未返回 @iot.count，count 只是 $top=1 首页条数"}


def main():
    base = (os.environ.get("ISTSOS_BASE_URL") or "").strip().rstrip("/")
    result = {"probe": PROBE_NAME, "version": PROBE_VERSION,
              "base_url": base or None, "configured": bool(base),
              "http_methods_used": ["GET"]}
    if not base:
        result.update({"ok": False, "ready": False,
                       "error_code": "NOT_CONFIGURED",
                       "message": "未配置 ISTSOS_BASE_URL，未发出任何请求；"
                                  "请把 STA 服务端基地址写入该环境变量"
                                  "（探针不带任何默认端点）"})
        print(json.dumps(result, ensure_ascii=False))
        return 1
    if not (base.startswith("http://") or base.startswith("https://")):
        result.update({"ok": False, "ready": False,
                       "error_code": "BAD_URL",
                       "message": "ISTSOS_BASE_URL 必须以 http:// 或 "
                                  "https:// 开头"})
        print(json.dumps(result, ensure_ascii=False))
        return 1
    try:
        landing = _get_json(base)
        names = [v.get("name") for v in landing.get("value", [])
                 if isinstance(v, dict)]
        result["root"] = {"ok": True, "landing_entries": names}
    except ProbeError as e:
        result["root"] = {"ok": False, "error_code": e.error_code,
                          "message": e.message}
    result["things"] = _count(base, "Things")
    result["datastreams"] = _count(base, "Datastreams")
    result["ready"] = bool(result["root"].get("ok"))
    result["ok"] = result["ready"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
