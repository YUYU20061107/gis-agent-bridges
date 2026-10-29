# -*- coding: utf-8 -*-
"""
probe_api.py — PostGIS 消费侧只读桥连通探针（纯标准库，只读）

在把数据库交给 MCP 服务端之前，先用这个脚本独立探一次目标库，
结果留档。探针与 live/mcp_server.py 同口径：连接只走 psql 子进程
与 PG* 环境变量；只执行固定模板（SELECT 1、PostGIS 版本、允许表
的几何列清单）；不读取、不输出 PGPASSWORD 的值。

依次探：psql 可用性 → SELECT 1 → PostGIS_Version() → 每个允许表
在 geometry_columns 里的登记。任何一步失败都如实记进对应字段，
不中断后续探针。POSTGIS_ALLOWED_TABLES 未配置时 geometry_columns
部分记 NOT_CONFIGURED，不猜表名。

用法：python3 scripts/probe_api.py
退出码：0 = SELECT 1 与 PostGIS 版本都探通；1 = psql 不可用或探针失败。
注意：探通只证明模板在目标库上能跑；数值对账（行数、范围）须按
docs/CALIBRATION.md 用桥之外的独立来源完成。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import postgis_bridge as gb  # noqa: E402

PROBE_NAME = "postgis-consumer-bridge"
PROBE_VERSION = "0.1.0"


def _try(fn):
    try:
        return {"ok": True, "value": fn()}
    except gb.BridgeError as e:
        return {"ok": False, "error_code": e.error_code,
                "message": e.message}


def main():
    result = {"probe": PROBE_NAME, "version": PROBE_VERSION,
              "psql": gb.psql_path(),
              "psql_available": gb.psql_available(),
              "connection_env": gb.connection_env_status(),
              "allowed_tables": sorted(gb.allowed_tables())}
    if not result["psql_available"]:
        result.update({"ok": False, "ready": False,
                       "error_code": "PSQL_NOT_AVAILABLE",
                       "message": "找不到 psql 可执行文件，未发出任何查询；"
                                  "请安装 PostgreSQL 客户端或用 "
                                  "POSTGIS_PSQL 指定路径"})
        print(json.dumps(result, ensure_ascii=False))
        return 1
    probe = _try(lambda: gb.run_psql(gb.PROBE_SQL).strip())
    result["select1"] = probe
    version = _try(lambda: gb.run_psql(gb.VERSION_SQL).strip()[:120])
    result["postgis_version"] = version
    tables = {}
    if not result["allowed_tables"]:
        result["geometry_columns"] = {
            "ok": False, "error_code": "NOT_CONFIGURED",
            "message": "POSTGIS_ALLOWED_TABLES 未配置，未查任何表"}
    else:
        for table in result["allowed_tables"]:
            tables[table] = _try(lambda t=table: gb.geom_columns(t))
        result["geometry_columns"] = {"ok": True, "tables": tables}
    result["ready"] = bool(probe.get("ok") and version.get("ok"))
    result["ok"] = result["ready"]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
