# -*- coding: utf-8 -*-
"""
probe_api.py — STAC 消费侧只读桥连通探针（纯标准库，只读）

在把基地址交给 MCP 服务端之前，先用这个脚本独立探一次目标
STAC 目录，结果留档。探针与 live/mcp_server.py 同口径：基
地址只从环境变量 STAC_BASE_URL 读，代码不带任何默认端点；
只发 GET；超时 10 秒、单次响应读取上限 2 MiB。

依次探：落地页（目录 id 与 conformsTo）→ 集合计数 → 首个
集合的 id。不做检索（检索留给校准工单按已知集合对账）。
任何一步失败都如实记进对应字段，不中断后续探针。未配置
STAC_BASE_URL 时输出结构化 NOT_CONFIGURED 并以退出码 1
结束，不发出任何请求。

用法：STAC_BASE_URL=<STAC 根地址> python3 scripts/probe_api.py
退出码：0 = 落地页可达且是合法 STAC 目录；1 = 未配置/不可达。
注意：探通只证明 STAC 协议级互通，不等于已按
docs/CALIBRATION.md 完成对账校准。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stac_bridge as sb  # noqa: E402

PROBE_NAME = "stac-consumer-bridge"
PROBE_VERSION = "0.1.0"


def _try(fn):
    try:
        return {"ok": True, "value": fn()}
    except sb.BridgeError as e:
        out = {"ok": False, "error_code": e.error_code,
               "message": e.message}
        if e.http_status is not None:
            out["http_status"] = e.http_status
        return out


def main():
    base = sb.base_url()
    result = {"probe": PROBE_NAME, "version": PROBE_VERSION,
              "base_url": base, "configured": bool(base),
              "api_key_configured": sb.api_key_configured(),
              "http_methods_used": ["GET"]}
    if not base:
        result.update({"ok": False, "ready": False,
                       "error_code": "NOT_CONFIGURED",
                       "message": "未配置 STAC_BASE_URL，未发出任何请求；"
                                  "请把 STAC API 根地址写入该环境变量"
                                  "（探针不带任何默认端点）"})
        print(json.dumps(result, ensure_ascii=False))
        return 1
    if not (base.startswith("http://") or base.startswith("https://")):
        result.update({"ok": False, "ready": False,
                       "error_code": "BAD_URL",
                       "message": "STAC_BASE_URL 必须以 http:// 或 "
                                  "https:// 开头"})
        print(json.dumps(result, ensure_ascii=False))
        return 1
    landing = _try(lambda: sb.http_get(base))
    if landing.get("ok"):
        data = landing["value"]
        result["landing"] = {"ok": True, "id": data.get("id"),
                             "title": data.get("title"),
                             "conforms_to": len(data.get("conformsTo") or [])}
    else:
        result["landing"] = landing
    cols = _try(lambda: sb.fetch_collections())
    if cols.get("ok"):
        items, meta = cols["value"]
        result["collections"] = {
            "ok": True, "count": len(items),
            "first_id": (items[0].get("id") if items else None),
            "truncated": meta["truncated"]}
    else:
        result["collections"] = cols
    result["ready"] = bool(result["landing"].get("ok"))
    result["ok"] = result["ready"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
