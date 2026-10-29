# -*- coding: utf-8 -*-
"""
mcp_server.py — PostGIS 消费侧只读桥 MCP 服务端（stdio，纯标准库，v0.1）

定位：PostGIS 是跑在 PostgreSQL 里的空间扩展，数据与空间函数都在
数据库内；本服务端不实现任何空间算法，只做消费侧的一段：通过固定
的参数化查询模板取回表的几何列清单、属性列、行数与范围，或把样本
要素导出成 GeoJSON 文件，供后续桌面 GIS 桥（如本仓 qgis/ 包）加载。
它不是 PostGIS / PostgreSQL 官方组件，与其官方项目无隶属关系。

工具（6 个，全部只读；本包 v0.1 没有任何写库工具）：
  postgis_ping                连通性检查
  postgis_discover            环境发现：psql 可用性、连接环境变量状态、
                              允许表集合、SELECT 1 与 PostGIS 版本探针
  postgis_list_spatial_tables 允许集合内各表的几何列清单
                              （geometry_columns 固定模板＋绑定变量）
  postgis_table_columns       某允许表的属性列清单（固定模板）
  postgis_table_summary       某允许表的行数与几何范围（ST_Extent）
  postgis_export_geojson      把某允许表的前 N 个要素导出为 GeoJSON
                              文件（写调用方指定的新文件；N 硬上限 1000）
—— 刻意不提供任意 SQL 执行工具：SQL 只有 scripts/postgis_bridge.py
   里写死的固定模板，表名须过标识符正则＋ POSTGIS_ALLOWED_TABLES
   允许集合双重校验，几何列名须再经 geometry_columns 核对归属，
   其余标量一律以 psql 变量传入。数据库访问走 psql 子进程参数数组，
   不经 shell、不拼连接串。

token 守卫（常开）：每次 tools/call 须在参数里带 _token 且与
POSTGIS_BRIDGE_TOKEN 环境变量、或 token 文件
~/.postgis-agent-bridge.token 的内容一致，否则以 BAD_TOKEN 拒绝。
两者都未配置时，服务端启动即生成随机 token 写入该文件（权限 0600）
并在 stderr 打印路径。本服务端走 stdio，不监听任何网络端口；唯一的
网络连接是 psql 按 PG* 环境变量连向你自己的 PostgreSQL。

环境变量：
  POSTGIS_BRIDGE_TOKEN    token（优先于 token 文件）
  PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD
                          libpq 标准连接环境变量，由 psql 自行读取；
                          本服务端不读、不记录 PGPASSWORD 的值
  POSTGIS_ALLOWED_TABLES  允许查询的表名（逗号分隔，查库工具必填）
  POSTGIS_EXPORT_DIR      导出根目录（可选，设置后导出只能落在其中）
  POSTGIS_PSQL            psql 路径（默认走 PATH）
每次查库工具调用都会往 ~/.postgis-agent-bridge/runs.jsonl 追加一条
记录（工具名、表名、状态、耗时；不含连接密码）。日志写 stderr，
stdout 只走 MCP 协议。

证据口径：本包未经实机校准（开发机无 PostgreSQL+PostGIS 环境），
只通过协议级自检（live/selftest.py，含假 psql 替身）；不要把自检
通过当作已在真实 PostGIS 上验证。实机校准工单见 docs/CALIBRATION.md。
"""
import io
import json
import os
import secrets
import sys
import time
from datetime import datetime

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "postgis-consumer-bridge"
SERVER_VERSION = "0.1.0"
TOKEN_FILE = os.path.join(os.path.expanduser("~"),
                          ".postgis-agent-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"), ".postgis-agent-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "runs.jsonl")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))

import postgis_bridge as gb  # noqa: E402


def log(*a):
    print("[postgis-mcp]", *a, file=sys.stderr, flush=True)

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
    tok = os.environ.get("POSTGIS_BRIDGE_TOKEN")
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


def _run_tool(tool, table, fn):
    """统一计时/记账/错误转译包装。"""
    t0 = time.time()
    try:
        result = fn()
    except gb.BridgeError as e:
        journal({"tool": tool, "table": table, "status": "error",
                 "error_code": e.error_code})
        return _bridge_error(e)
    result = dict(result)
    result["duration_s"] = round(time.time() - t0, 3)
    journal({"tool": tool, "table": table, "status": "ok",
             "duration_s": result["duration_s"]})
    return result


# ------------------------------------------------------------------ tools
def tool_ping(args):
    return {"ok": True, "pong": True, "bridge": SERVER_NAME,
            "version": SERVER_VERSION, "mode": "consumer-readonly",
            "psql_available": gb.psql_available()}


def tool_discover(args):
    info = {"ok": True, "mode": "consumer-readonly",
            "role": "消费侧只读桥：空间数据与函数都在 PostGIS 里，"
                    "本桥只按固定模板取结构、计数、范围与样本要素",
            "official_note": "本包不是 PostGIS / PostgreSQL 官方组件，"
                             "与其官方项目无隶属关系",
            "psql": gb.psql_path(), "psql_available": gb.psql_available(),
            "connection_env": gb.connection_env_status(),
            "allowed_tables": sorted(gb.allowed_tables()),
            "export_dir": os.environ.get("POSTGIS_EXPORT_DIR") or None,
            "export_limit_max": gb.MAX_EXPORT_LIMIT,
            "token_guard": "on",
            "journal_file": JOURNAL_FILE,
            "calibration": "未实机校准（协议自检级）；见 docs/CALIBRATION.md"}
    if gb.psql_available():
        try:
            out = gb.run_psql(gb.PROBE_SQL)
            info["probe_select1"] = {"ok": out.strip() == "1",
                                     "raw": out.strip()[:50]}
        except gb.BridgeError as e:
            info["probe_select1"] = {"ok": False,
                                     "error_code": e.error_code,
                                     "message": e.message}
        try:
            out = gb.run_psql(gb.VERSION_SQL)
            info["postgis_version"] = {"ok": True,
                                        "raw": out.strip()[:120]}
        except gb.BridgeError as e:
            info["postgis_version"] = {"ok": False,
                                       "error_code": e.error_code,
                                       "message": e.message}
    else:
        info["probe_select1"] = {"ok": False,
                                 "error_code": "PSQL_NOT_AVAILABLE",
                                 "message": "psql 不可用，未做连通探针"}
        info["postgis_version"] = {"ok": False,
                                   "error_code": "PSQL_NOT_AVAILABLE",
                                   "message": "psql 不可用，未查 PostGIS 版本"}
    return info


def tool_list_spatial_tables(args):
    allow = sorted(gb.allowed_tables())
    if not allow:
        return _bridge_error(gb.BridgeError(
            "NOT_CONFIGURED",
            "POSTGIS_ALLOWED_TABLES 未配置：不知道该查哪些表就不猜"))

    def _fn():
        tables = []
        for table in allow:
            cols = gb.geom_columns(table)
            tables.append({"table": table, "geometry_columns": cols,
                           "is_spatial": len(cols) > 0})
        return {"ok": True, "tables": tables, "count": len(tables)}
    return _run_tool("list_spatial_tables", None, _fn)


def tool_table_columns(args):
    try:
        table = gb.validate_table(args.get("table"))
    except gb.BridgeError as e:
        return _bridge_error(e)

    def _fn():
        out = gb.run_psql(gb.COLUMNS_SQL, {"tbl": table})
        cols = gb.parse_columns(out)
        return {"ok": True, "table": table, "columns": cols,
                "count": len(cols)}
    return _run_tool("table_columns", table, _fn)


def tool_table_summary(args):
    try:
        table = gb.validate_table(args.get("table"))
    except gb.BridgeError as e:
        return _bridge_error(e)

    def _fn():
        count = gb.parse_count(gb.run_psql(gb.render_sql(gb.COUNT_SQL, table)))
        geom = gb.resolve_geom(table, args.get("geom"))
        extent = gb.parse_extent(gb.run_psql(
            gb.render_sql(gb.EXTENT_SQL, table, geom)))
        result = {"ok": True, "table": table, "geom": geom,
                  "row_count": count, "extent": extent}
        if extent is None:
            result["note"] = "范围为空：该表当前无要素（ST_Extent 为 NULL）"
        return result
    return _run_tool("table_summary", table, _fn)


def tool_export_geojson(args):
    try:
        table = gb.validate_table(args.get("table"))
        limit = gb.validate_limit(args.get("limit"),
                                  gb.DEFAULT_EXPORT_LIMIT,
                                  gb.MAX_EXPORT_LIMIT)
        path = gb.resolve_export_path(args.get("filename"),
                                      args.get("output_dir"))
    except gb.BridgeError as e:
        return _bridge_error(e)

    def _fn():
        geom = gb.resolve_geom(table, args.get("geom"))
        sql = gb.render_sql(gb.EXPORT_SQL, table, geom)
        out = gb.run_psql(sql, {"lim": str(limit)})
        text = out.strip()
        try:
            data = json.loads(text) if text else None
        except Exception as e:
            raise gb.BridgeError("BAD_GEOJSON",
                                 "GeoJSON 解析失败: %s" % e)
        if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
            raise gb.BridgeError("BAD_GEOJSON",
                                 "数据库返回的不是 FeatureCollection：%r"
                                 % (text[:200],))
        features = data.get("features") or []
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            raise gb.BridgeError("WRITE_FAILED", "导出文件写入失败: %s" % e)
        return {"ok": True, "table": table, "geom": geom, "path": path,
                "bytes": os.path.getsize(path), "features": len(features),
                "limit": limit,
                "next_step": "可用本仓 qgis/ 桥的 qgis_add_layer_from_path "
                             "把该文件加载进 QGIS（其校准状态见 qgis 包 README）"}
    return _run_tool("export_geojson", table, _fn)


_STR = {"type": "string"}
_INT = {"type": "integer"}

_TABLE_PROP = dict(_STR, description="表名（必填）：须只含 [A-Za-z0-9_] "
                   "且在 POSTGIS_ALLOWED_TABLES 允许集合内；目标表须在 "
                   "public schema")
_GEOM_PROP = dict(_STR, description="几何列名（可选）：须是该表在 "
                  "geometry_columns 里登记的列；省略时仅当该表恰有一个"
                  "几何列才自动采用")

TOOL_DEFS = [
    ("postgis_ping", "连通性检查：桥是否在线，并回报 psql 是否可用", {}),
    ("postgis_discover", "环境发现：psql 可用性、连接环境变量设置状态（密码只报是否设置）、允许表集合、SELECT 1 与 PostGIS 版本只读探针（校准用）", {}),
    ("postgis_list_spatial_tables", "列出允许集合内各表在 geometry_columns 里登记的几何列（列名、类型、SRID）；无登记的表如实标 is_spatial=false",
     {}),
    ("postgis_table_columns", "用固定模板列出某个允许表的属性列（列名与数据类型，information_schema）",
     {"table": _TABLE_PROP}),
    ("postgis_table_summary", "某个允许表的只读统计：行数（count）与几何范围（ST_Extent）；空表范围为 null 并注明",
     {"table": _TABLE_PROP, "geom": _GEOM_PROP}),
    ("postgis_export_geojson", "用固定模板把某个允许表的前 N 个要素经 ST_AsGeoJSON 导出为 GeoJSON 文件（写调用方指定的新文件；filename 只许文件名、须 .geojson；落点受 POSTGIS_EXPORT_DIR 约束；N 上限 1000，超限拒绝）",
     {"table": _TABLE_PROP, "geom": _GEOM_PROP,
      "limit": dict(_INT, description="导出条数（可选，默认 100，范围 1..1000）"),
      "filename": dict(_STR, description="导出文件名（必填，只给文件名，如 parcels_sample.geojson）"),
      "output_dir": dict(_STR, description="输出目录（可选；设置了 POSTGIS_EXPORT_DIR 时必须在其内）")}),
]

HANDLERS = {
    "postgis_ping": tool_ping,
    "postgis_discover": tool_discover,
    "postgis_list_spatial_tables": tool_list_spatial_tables,
    "postgis_table_columns": tool_table_columns,
    "postgis_table_summary": tool_table_summary,
    "postgis_export_geojson": tool_export_geojson,
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
        JOURNAL_FILE, gb.psql_path()))
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
