# -*- coding: utf-8 -*-
"""
mcp_server.py — pgRouting 消费侧只读桥 MCP 服务端（stdio，纯标准库，v0.1）

定位：pgRouting 是跑在 PostgreSQL 里的路径计算扩展，计算发生在数据库内；
本服务端不实现任何路径算法，只做消费侧的一段：通过固定的参数化查询
模板调用 pgr_dijkstra 等函数，把结果取回、统计或导出成 GeoJSON 文件，
供后续桌面 GIS 桥（如本仓 qgis/ 包）加载。它不是 pgRouting 官方组件，
与 pgRouting / PostGIS 官方项目无隶属关系。

工具（5 个，全部只读；本包 v0.1 没有任何写库工具）：
  pgrouting_ping               连通性检查
  pgrouting_discover           环境发现：psql 可用性、连接环境变量状态、
                               允许表集合、只读探针 SELECT 1 结果（校准用）
  pgrouting_route_dijkstra     固定模板查一条最短路径（节点序列＋代价）
  pgrouting_export_route_geojson 把一条路径经 ST_AsGeoJSON 导出为
                               GeoJSON 文件（写调用方指定的新文件）
  pgrouting_network_summary    边表只读统计：节点数 / 边数
—— 刻意不提供任意 SQL 执行工具：SQL 只有 scripts/pgrouting_bridge.py 里
   写死的三条模板，边表名须过标识符正则＋ PGROUTING_ALLOWED_TABLES
   允许集合双重校验，起终点 id 与 directed 在 Python 侧强转后才进 psql
   变量。数据库访问走 psql 子进程参数数组，不经 shell、不拼连接串。

token 守卫（常开）：每次 tools/call 须在参数里带 _token 且与
PGROUTING_BRIDGE_TOKEN 环境变量、或 token 文件
~/.pgrouting-agent-bridge.token 的内容一致，否则以 BAD_TOKEN 拒绝。
两者都未配置时，服务端启动即生成随机 token 写入该文件（权限 0600）
并在 stderr 打印路径。本服务端走 stdio，不监听任何网络端口；唯一的
网络连接是 psql 按 PG* 环境变量连向你自己的 PostgreSQL。

环境变量：
  PGROUTING_BRIDGE_TOKEN    token（优先于 token 文件）
  PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD
                            libpq 标准连接环境变量，由 psql 自行读取；
                            本服务端不读、不记录 PGPASSWORD 的值
  PGROUTING_ALLOWED_TABLES  允许查询的边表名（逗号分隔，查库工具必填）
  PGROUTING_EXPORT_DIR      导出根目录（可选，设置后导出只能落在其中）
  PGROUTING_PSQL            psql 路径（默认走 PATH）
每次查库工具调用都会往 ~/.pgrouting-agent-bridge/runs.jsonl 追加一条
记录（工具名、表名、状态、耗时；不含连接密码与查询参数原文中的敏感项）。
日志写 stderr，stdout 只走 MCP 协议。

证据口径：本包未经实机校准（开发机无 PostgreSQL+pgRouting 环境），
只通过协议级自检（live/selftest.py，含假 psql 替身）；不要把自检通过
当作已在真实 pgRouting 上验证。实机校准工单见 docs/CALIBRATION.md。
"""
import io
import json
import os
import secrets
import sys
import time
from datetime import datetime

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "pgrouting-consumer-bridge"
SERVER_VERSION = "0.1.0"
TOKEN_FILE = os.path.join(os.path.expanduser("~"),
                          ".pgrouting-agent-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"), ".pgrouting-agent-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "runs.jsonl")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))

import pgrouting_bridge as pb  # noqa: E402


def log(*a):
    print("[pgrouting-mcp]", *a, file=sys.stderr, flush=True)

# ---- 序列化净化（与仓内各包同口径） ----
try:
    _TEXT = unicode  # noqa: F821
except NameError:
    _TEXT = str


def _dec(b):
    """bytes -> 文本。解码顺序：UTF-8 -> 系统文件系统编码 -> GBK -> latin-1。"""
    if isinstance(b, _TEXT):
        return b
    if not isinstance(b, (bytes, bytearray)):
        return "%s" % (b,)
    try:
        return bytes(b).decode("utf-8")
    except Exception:
        pass
    for enc in (sys.getfilesystemencoding(), "gbk", "latin-1"):
        if not enc:
            continue
        try:
            return bytes(b).decode(enc)
        except Exception:
            continue
    return bytes(b).decode("utf-8", "replace")


def _to_text(obj):
    """递归净化待 JSON 序列化的对象，保证 dumps 不会因异类对象崩溃。"""
    if isinstance(obj, dict):
        return dict((_to_text(k), _to_text(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [_to_text(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return _dec(obj)
    if obj is None or isinstance(obj, (_TEXT, bool, int, float)):
        return obj
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return "%s" % (obj,)


def _lock_stdio_utf8():
    """把 stdin/stdout 锁定为 UTF-8；只在 main() 调用一次。"""
    for _name in ("stdout", "stdin"):
        _stream = getattr(sys, _name, None)
        _buf = getattr(_stream, "buffer", None)
        if _buf is None or getattr(_stream, "encoding", None) == "utf-8":
            continue
        try:
            setattr(sys, _name, io.TextIOWrapper(_buf, encoding="utf-8",
                                                 errors="replace"))
        except Exception:
            pass


# ------------------------------------------------------------------ token
def expected_token():
    tok = os.environ.get("PGROUTING_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def ensure_token():
    """token 守卫常开：无任何配置时生成随机 token 写入文件（0600）。"""
    if expected_token():
        return
    tok = secrets.token_hex(16)
    try:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tok)
        log("generated bridge token at %s (0600)" % TOKEN_FILE)
    except Exception as e:
        log("WARNING: cannot write token file %s: %s" % (TOKEN_FILE, e))


def journal(entry):
    try:
        os.makedirs(JOURNAL_DIR, exist_ok=True)
        entry = dict(entry)
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _bridge_error(e):
    return {"ok": False, "error_code": e.error_code, "message": e.message}


# ------------------------------------------------------------------ tools
def tool_ping(args):
    return {"ok": True, "pong": True, "bridge": SERVER_NAME,
            "version": SERVER_VERSION, "mode": "consumer-readonly",
            "psql_available": pb.psql_available()}


def tool_discover(args):
    info = {"ok": True, "mode": "consumer-readonly",
            "role": "消费侧只读桥：路径由 pgRouting 在数据库内计算，"
                    "本桥只按固定模板取结果与落文件",
            "official_note": "本包不是 pgRouting 官方组件，与 pgRouting / "
                             "PostGIS 官方项目无隶属关系",
            "psql": pb.psql_path(), "psql_available": pb.psql_available(),
            "connection_env": pb.connection_env_status(),
            "allowed_tables": sorted(pb.allowed_tables()),
            "export_dir": os.environ.get("PGROUTING_EXPORT_DIR") or None,
            "token_guard": "on",
            "journal_file": JOURNAL_FILE,
            "calibration": "未实机校准（协议自检级）；见 docs/CALIBRATION.md"}
    if pb.psql_available():
        try:
            out = pb.run_psql("SELECT 1;")
            info["probe_select1"] = {"ok": out.strip() == "1",
                                     "raw": out.strip()[:50]}
        except pb.BridgeError as e:
            info["probe_select1"] = {"ok": False,
                                     "error_code": e.error_code,
                                     "message": e.message}
    else:
        info["probe_select1"] = {"ok": False,
                                 "error_code": "PSQL_NOT_AVAILABLE",
                                 "message": "psql 不可用，未做连通探针"}
    return info


def _route_params(args):
    table = pb.validate_table(args.get("table"))
    start_id = pb.validate_node_id(args.get("start_id"), "start_id")
    end_id = pb.validate_node_id(args.get("end_id"), "end_id")
    directed = pb.validate_directed(args.get("directed"))
    return table, start_id, end_id, directed


def tool_route_dijkstra(args):
    t0 = time.time()
    try:
        table, start_id, end_id, directed = _route_params(args)
        sql = pb.render_sql(pb.ROUTE_SQL, table)
        out = pb.run_psql(sql, pb.route_variables(start_id, end_id, directed))
        rows = pb.parse_route_rows(out)
    except pb.BridgeError as e:
        journal({"tool": "route_dijkstra", "table": args.get("table"),
                 "status": "error", "error_code": e.error_code})
        return _bridge_error(e)
    duration = round(time.time() - t0, 3)
    journal({"tool": "route_dijkstra", "table": table, "status": "ok",
             "rows": len(rows), "duration_s": duration})
    result = {"ok": True, "table": table, "start_id": start_id,
              "end_id": end_id, "directed": directed,
              "found": len(rows) > 0, "hops": max(0, len(rows) - 1),
              "total_cost": (rows[-1]["agg_cost"] if rows else None),
              "rows": rows, "duration_s": duration}
    if not rows:
        result["note"] = "pgr_dijkstra 无返回行：起终点之间无路径或节点不存在"
    return result


def tool_export_route_geojson(args):
    t0 = time.time()
    try:
        table, start_id, end_id, directed = _route_params(args)
        path = pb.resolve_export_path(args.get("filename"),
                                      args.get("output_dir"))
        sql = pb.render_sql(pb.ROUTE_GEOJSON_SQL, table)
        out = pb.run_psql(sql, pb.route_variables(start_id, end_id, directed))
        text = out.strip()
        data = json.loads(text) if text else None
        if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
            raise pb.BridgeError("BAD_GEOJSON",
                                 "数据库返回的不是 FeatureCollection：%r"
                                 % (text[:200],))
    except pb.BridgeError as e:
        journal({"tool": "export_route_geojson", "table": args.get("table"),
                 "status": "error", "error_code": e.error_code})
        return _bridge_error(e)
    except Exception as e:
        journal({"tool": "export_route_geojson", "table": args.get("table"),
                 "status": "error", "error_code": "BAD_GEOJSON"})
        return {"ok": False, "error_code": "BAD_GEOJSON",
                "message": "GeoJSON 解析失败: %s" % e}
    features = data.get("features") or []
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        journal({"tool": "export_route_geojson", "table": table,
                 "status": "error", "error_code": "WRITE_FAILED"})
        return {"ok": False, "error_code": "WRITE_FAILED",
                "message": "导出文件写入失败: %s" % e}
    duration = round(time.time() - t0, 3)
    journal({"tool": "export_route_geojson", "table": table, "status": "ok",
             "features": len(features), "path": path,
             "duration_s": duration})
    return {"ok": True, "table": table, "start_id": start_id,
            "end_id": end_id, "directed": directed, "path": path,
            "bytes": os.path.getsize(path), "features": len(features),
            "duration_s": duration,
            "next_step": "可用本仓 qgis/ 桥的 qgis_add_layer_from_path "
                         "把该文件加载进 QGIS（其校准状态见 qgis 包 README）"}


def tool_network_summary(args):
    t0 = time.time()
    try:
        table = pb.validate_table(args.get("table"))
        sql = pb.render_sql(pb.SUMMARY_SQL, table)
        out = pb.run_psql(sql)
        summary = pb.parse_summary(out)
    except pb.BridgeError as e:
        journal({"tool": "network_summary", "table": args.get("table"),
                 "status": "error", "error_code": e.error_code})
        return _bridge_error(e)
    duration = round(time.time() - t0, 3)
    journal({"tool": "network_summary", "table": table, "status": "ok",
             "duration_s": duration})
    return {"ok": True, "table": table,
            "node_count": summary["node_count"],
            "edge_count": summary["edge_count"], "duration_s": duration}


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}

_TABLE_PROP = dict(_STR, description="边表名（必填）：标准 pgRouting 边表"
                   "（id/source/target/cost/reverse_cost[/geom]）；须只含 "
                   "[A-Za-z0-9_] 且在 PGROUTING_ALLOWED_TABLES 允许集合内")
_DIRECTED_PROP = dict(_BOOL, description="是否有向（可选，默认 true）")

TOOL_DEFS = [
    ("pgrouting_ping", "连通性检查：桥是否在线，并回报 psql 是否可用", {}),
    ("pgrouting_discover", "环境发现：psql 可用性、连接环境变量设置状态（密码只报是否设置）、允许表集合、SELECT 1 只读探针（校准用）", {}),
    ("pgrouting_route_dijkstra", "用固定 pgr_dijkstra 模板查一条最短路径：返回节点/边序列与累计代价；无任意 SQL 入口",
     {"table": _TABLE_PROP,
      "start_id": dict(_INT, description="起点节点 id（必填，整数）"),
      "end_id": dict(_INT, description="终点节点 id（必填，整数）"),
      "directed": _DIRECTED_PROP}),
    ("pgrouting_export_route_geojson", "用固定模板把一条路径经 ST_AsGeoJSON 导出为 GeoJSON 文件（写调用方指定的新文件；filename 只许文件名、须 .geojson；落点受 PGROUTING_EXPORT_DIR 约束）",
     {"table": _TABLE_PROP,
      "start_id": dict(_INT, description="起点节点 id（必填，整数）"),
      "end_id": dict(_INT, description="终点节点 id（必填，整数）"),
      "directed": _DIRECTED_PROP,
      "filename": dict(_STR, description="导出文件名（必填，只给文件名，如 route_1_9.geojson）"),
      "output_dir": dict(_STR, description="输出目录（可选；设置了 PGROUTING_EXPORT_DIR 时必须在其内）")}),
    ("pgrouting_network_summary", "边表只读统计：节点数（source/target 去重）与边数",
     {"table": _TABLE_PROP}),
]

HANDLERS = {
    "pgrouting_ping": tool_ping,
    "pgrouting_discover": tool_discover,
    "pgrouting_route_dijkstra": tool_route_dijkstra,
    "pgrouting_export_route_geojson": tool_export_route_geojson,
    "pgrouting_network_summary": tool_network_summary,
}


def tools_list():
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props in TOOL_DEFS]


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools_list()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = dict(params.get("arguments") or {})
        supplied = args.pop("_token", None)
        expect = expected_token()
        if not expect or supplied != expect:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(
                    {"ok": False, "error_code": "BAD_TOKEN",
                     "message": "token 缺失或不正确"}, ensure_ascii=False)}],
                "isError": True}}
        handler = HANDLERS.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "unknown tool: %s" % name}],
                "isError": True}}
        try:
            result = handler(args)
            text = json.dumps(_to_text(result), ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": "tool failed: %s" % e}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    _lock_stdio_utf8()
    ensure_token()
    log("starting; journal=%s token_guard=on psql=%s" % (
        JOURNAL_FILE, pb.psql_path()))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:
            log("bad json:", e)
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(_to_text(resp), ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
