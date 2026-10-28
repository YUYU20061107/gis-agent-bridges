# -*- coding: utf-8 -*-
"""
probe_api.py — pgRouting 消费侧桥校准探针（纯标准库，只读）

首次部署或 PostgreSQL/pgRouting 版本变更时运行一次，输出单行 JSON：
psql 可用性与版本、连接环境变量状态（密码只报是否设置）、只读探针
（SELECT 1 / PostGIS 版本 / pgRouting 版本 / 允许表中第一张表的
network_summary 试算）。全部探针都是只读 SELECT；任何一步失败都
如实记进对应字段，不中断后续探针，更不许据此自行扩展动作。

用法：python3 scripts/probe_api.py
退出码：0 = psql 可用且 SELECT 1 通过；1 = 环境未就绪（按 JSON 定位）。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pgrouting_bridge as pb  # noqa: E402


def _run(argv):
    proc = subprocess.run(argv, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=pb.psql_timeout())
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace").strip(),
            proc.stderr.decode("utf-8", "replace").strip())


def _probe_sql(sql, variables=None):
    try:
        return {"ok": True, "output": pb.run_psql(sql, variables).strip()[:300]}
    except pb.BridgeError as e:
        return {"ok": False, "error_code": e.error_code, "message": e.message}


def main():
    result = {"probe": "pgrouting-consumer-bridge", "version": "0.1.0",
              "psql": pb.psql_path(), "psql_available": pb.psql_available(),
              "connection_env": pb.connection_env_status(),
              "allowed_tables": sorted(pb.allowed_tables())}
    if result["psql_available"]:
        try:
            rc, out, _err = _run([pb.psql_path(), "--version"])
            result["psql_version"] = out if rc == 0 else None
        except Exception as e:
            result["psql_version"] = None
            result["psql_version_error"] = str(e)
        result["select1"] = _probe_sql("SELECT 1;")
        result["postgis"] = _probe_sql("SELECT postgis_lib_version();")
        result["pgrouting"] = _probe_sql("SELECT pgr_version();")
        allow = sorted(pb.allowed_tables())
        if allow:
            try:
                table = pb.validate_table(allow[0])
                out = pb.run_psql(pb.render_sql(pb.SUMMARY_SQL, table))
                result["summary_probe"] = dict(pb.parse_summary(out),
                                               table=table, ok=True)
            except pb.BridgeError as e:
                result["summary_probe"] = {"ok": False,
                                           "error_code": e.error_code,
                                           "message": e.message}
    ready = bool(result["psql_available"] and
                 result.get("select1", {}).get("ok"))
    result["ready"] = ready
    print(json.dumps(result, ensure_ascii=False))
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
