# -*- coding: utf-8 -*-
"""
probe_api.py — GRASS GIS 无头桥环境探针（纯标准库，只读）

在把 GRASS 数据库交给 MCP 服务端之前，先用这个脚本独立探
一次本机环境，结果留档。探针与 live/mcp_server.py 同口径：
gisdbase 只从环境变量 GRASS_BRIDGE_GISDBASE 读；location
清单只看目录结构（带 PERMANENT 的子目录）；版本经
grass --version 取。探针不以 --exec 启动任何 GRASS 模块，
不写任何图层。

依次探：grass 可用性与版本 → gisdbase 是否配置/存在 →
location 清单 → 首个 location 的 mapset 清单。任何一步
失败都如实记进对应字段。grass 不可用时以退出码 1 结束。

用法：GRASS_BRIDGE_GISDBASE=<数据库根> python3 scripts/probe_api.py
退出码：0 = grass 可用且 gisdbase 已配置并存在；1 = 否则。
注意：探通只证明批处理入口存在；模块级对账须按
docs/CALIBRATION.md 在真实数据上完成。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import grass_bridge as gb  # noqa: E402

PROBE_NAME = "grass-headless-bridge"
PROBE_VERSION = "0.1.0"


def main():
    base = gb.gisdbase()
    locations = gb.list_locations()
    result = {"probe": PROBE_NAME, "version": PROBE_VERSION,
              "grass": gb.grass_path(),
              "grass_available": gb.grass_available(),
              "grass_version": gb.grass_version(),
              "gisdbase": base,
              "gisdbase_configured": base is not None,
              "gisdbase_exists": bool(base) and os.path.isdir(base),
              "locations": locations}
    if locations:
        try:
            info = gb.location_info(locations[0])
            result["first_location"] = {
                "location": locations[0], "mapsets": info["mapsets"],
                "projection_name": info["projection"].get("name")}
        except gb.BridgeError as e:
            result["first_location"] = {"ok": False,
                                        "error_code": e.error_code,
                                        "message": e.message}
    result["ready"] = bool(result["grass_available"]
                           and result["gisdbase_exists"])
    result["ok"] = result["ready"]
    if not result["grass_available"]:
        result["error_code"] = "GRASS_NOT_AVAILABLE"
        result["message"] = "找不到 grass 可执行文件，未做任何调用"
    elif not base:
        result["error_code"] = "NOT_CONFIGURED"
        result["message"] = "GRASS_BRIDGE_GISDBASE 未配置"
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
