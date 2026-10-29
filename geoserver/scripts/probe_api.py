# -*- coding: utf-8 -*-
"""
probe_api.py — GeoServer 消费侧只读桥连通探针（纯标准库，只读）

在把基地址交给 MCP 服务端之前，先用这个脚本独立探一次目标
GeoServer，结果留档。探针与 live/mcp_server.py 同口径：基地址
只从环境变量 GEOSERVER_BASE_URL 读，代码不带任何默认端点；
只发 GET；超时 10 秒、单次响应读取上限 2 MiB。

依次探：/rest/about/version.json → 工作区计数 → 图层计数 →
WMS GetCapabilities 标题。任何一步失败都如实记进对应字段，不
中断后续探针。未配置 GEOSERVER_BASE_URL 时输出结构化
NOT_CONFIGURED 并以退出码 1 结束，不发出任何请求。

用法：GEOSERVER_BASE_URL=<基地址> python3 scripts/probe_api.py
退出码：0 = version 端点可达且是合法 JSON；1 = 未配置/不可达。
注意：探通只证明 REST 与 OGC 协议级互通，不等于已按
docs/CALIBRATION.md 完成对账校准。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geoserver_bridge as gs  # noqa: E402

PROBE_NAME = "geoserver-consumer-bridge"
PROBE_VERSION = "0.1.0"


def _try(fn):
    try:
        return {"ok": True, "value": fn()}
    except gs.BridgeError as e:
        out = {"ok": False, "error_code": e.error_code,
               "message": e.message}
        if e.http_status is not None:
            out["http_status"] = e.http_status
        return out


def main():
    base = gs.base_url()
    result = {"probe": PROBE_NAME, "version": PROBE_VERSION,
              "base_url": base, "configured": bool(base),
              "auth_configured": gs.auth_configured(),
              "http_methods_used": ["GET"]}
    if not base:
        result.update({"ok": False, "ready": False,
                       "error_code": "NOT_CONFIGURED",
                       "message": "未配置 GEOSERVER_BASE_URL，未发出任何"
                                  "请求；请把 GeoServer 基地址写入该"
                                  "环境变量（探针不带任何默认端点）"})
        print(json.dumps(result, ensure_ascii=False))
        return 1
    if not (base.startswith("http://") or base.startswith("https://")):
        result.update({"ok": False, "ready": False,
                       "error_code": "BAD_URL",
                       "message": "GEOSERVER_BASE_URL 必须以 http:// 或 "
                                  "https:// 开头"})
        print(json.dumps(result, ensure_ascii=False))
        return 1
    version = _try(lambda: (gs.get_json("about/version.json")
                            .get("about") or {}).get("Version"))
    result["version"] = version
    result["workspaces"] = _try(
        lambda: len(gs.parse_workspaces(gs.get_json("workspaces.json"))))
    result["layers"] = _try(
        lambda: len(gs.parse_layers(gs.get_json("layers.json"))))

    def _caps():
        _c, raw = gs.http_get(
            base + "/wms?service=WMS&request=GetCapabilities&version=1.3.0",
            accept="application/xml")
        return gs.parse_capabilities(raw, "wms").get("service_title")
    result["wms_title"] = _try(_caps)
    result["ready"] = bool(version.get("ok"))
    result["ok"] = result["ready"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
