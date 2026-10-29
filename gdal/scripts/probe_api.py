# -*- coding: utf-8 -*-
"""
probe_api.py — GDAL/OGR 工具桥环境探针（纯标准库，只读）

在把文件交给 MCP 服务端之前，先用这个脚本独立探一次本机
GDAL 工具环境，结果留档。探针与 live/mcp_server.py 同
口径：四件工具只调 --version 取版本；不打开任何数据文件；
不写任何文件。任何一件缺失都如实记进对应字段。

依次探：gdalinfo → ogrinfo → gdal_translate → ogr2ogr 的
路径、可用性与版本，并汇总可转换格式枚举。四件全可用时
退出码 0，否则 1（部分可用不算全绿，逐项以字段为准）。

用法：python3 scripts/probe_api.py
注意：探通只证明命令行工具存在；解析与转换口径须按
docs/CALIBRATION.md 在真实文件上对账。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gdal_bridge as gb  # noqa: E402

PROBE_NAME = "gdal-tool-bridge"
PROBE_VERSION = "0.1.0"


def _probe(path, label):
    avail = gb.tool_available(path)
    return {"path": path, "available": avail,
            "version": gb.tool_version(path, label) if avail else None}


def main():
    tools = {
        "gdalinfo": _probe(gb.gdalinfo_path(), "gdalinfo"),
        "ogrinfo": _probe(gb.ogrinfo_path(), "ogrinfo"),
        "gdal_translate": _probe(gb.gdal_translate_path(), "gdal_translate"),
        "ogr2ogr": _probe(gb.ogr2ogr_path(), "ogr2ogr"),
    }
    all_ok = all(t["available"] for t in tools.values())
    result = {"probe": PROBE_NAME, "version": PROBE_VERSION,
              "tools": tools,
              "raster_formats": gb.RASTER_FORMATS,
              "vector_formats": gb.VECTOR_FORMATS,
              "pam_policy": "子进程强制 GDAL_PAM_ENABLED=NO",
              "ready": all_ok, "ok": all_ok}
    if not all_ok:
        missing = [k for k, t in tools.items() if not t["available"]]
        result["error_code"] = "TOOLS_MISSING"
        result["message"] = "以下工具不可用：%s" % ", ".join(missing)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
