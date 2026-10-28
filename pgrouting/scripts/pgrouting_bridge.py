# -*- coding: utf-8 -*-
"""
pgrouting_bridge.py — pgRouting 消费侧桥的连接 / 校验 / SQL 模板库
（纯标准库，供 live/mcp_server.py 与 scripts/probe_api.py 共用）

定位：本库是消费侧工具箱——路径由 pgRouting 在数据库内算好，本库只负责
用固定的参数化查询模板把结果取出来、落成文件。它不提供任何任意 SQL
执行能力：

  * SQL 只有三条固定模板（dijkstra 路径 / 路径 GeoJSON / 边表统计），
    模板文本写死在本文件里，调用方没有任何入口能改动它；
  * 边表名只能以标识符形式进入模板，进入前必须同时通过两道校验：
    (1) 正则 ^[A-Za-z0-9_]+$（从字符集上排除引号、分号、空格等一切
        注入材料）；
    (2) 必须在环境变量 PGROUTING_ALLOWED_TABLES 配置的允许集合内；
    集合未配置时一切查库工具直接以 NOT_CONFIGURED 拒绝，不猜默认表；
  * 起终点节点 id 在 Python 侧强转 int 后才以 psql 变量传入，directed
    在 Python 侧强转 bool 后才以 true/false 字面量传入，两者都不会把
    调用方原文拼进 SQL；
  * 数据库访问一律走 psql 子进程的参数数组（subprocess list 形式），
    不经过 shell，不拼连接字符串；
  * 连接参数只从 libpq 标准环境变量读（PGHOST/PGPORT/PGDATABASE/
    PGUSER/PGPASSWORD），由 psql 进程自行从环境继承；本库不读取、
    不记录 PGPASSWORD 的值，日志与回报里最多出现“已设置/未设置”。

边表结构约定（标准 pgRouting 边表，osm2pgrouting 的 ways 一类）：
  id / source / target / cost / reverse_cost / geom
geom 仅 GeoJSON 导出需要（PostGIS）；纯路径与统计不依赖 geom 列。

环境变量：
  PGROUTING_PSQL            psql 可执行文件路径（默认 "psql"，走 PATH）
  PGROUTING_ALLOWED_TABLES  允许查询的边表名，逗号分隔（查库工具必填）
  PGROUTING_EXPORT_DIR      导出根目录（可选；设置后 output_dir 必须在其内）
  PGROUTING_PSQL_TIMEOUT    单次 psql 调用超时秒数（默认 30）
"""
import os
import re
import shutil
import subprocess

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
NODE_ID_RE = re.compile(r"^-?\d+$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class BridgeError(Exception):
    """带结构化错误码的桥内错误；mcp_server 会原样转成工具错误回报。"""

    def __init__(self, error_code, message):
        Exception.__init__(self, message)
        self.error_code = error_code
        self.message = message


# ------------------------------------------------------------------ 配置
def psql_path():
    return os.environ.get("PGROUTING_PSQL") or "psql"


def psql_available():
    p = psql_path()
    if os.path.sep in p or (os.path.altsep and os.path.altsep in p):
        return os.path.isfile(p)
    return shutil.which(p) is not None


def allowed_tables():
    raw = os.environ.get("PGROUTING_ALLOWED_TABLES") or ""
    return set(t.strip() for t in raw.split(",") if t.strip())


def psql_timeout():
    try:
        return max(1, int(os.environ.get("PGROUTING_PSQL_TIMEOUT") or 30))
    except Exception:
        return 30


def connection_env_status():
    """只回报连接环境变量的设置状态；PGPASSWORD 永远只报布尔。"""
    status = {}
    for key in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER"):
        status[key] = os.environ.get(key) or None
    status["PGPASSWORD_set"] = bool(os.environ.get("PGPASSWORD"))
    return status


# ------------------------------------------------------------------ 校验
def validate_table(table):
    if not isinstance(table, str) or not IDENT_RE.match(table or ""):
        raise BridgeError(
            "BAD_TABLE_NAME",
            "边表名非法：只允许 [A-Za-z0-9_]+ 的单个标识符，收到 %r" % (table,))
    allow = allowed_tables()
    if not allow:
        raise BridgeError(
            "NOT_CONFIGURED",
            "PGROUTING_ALLOWED_TABLES 未配置：出于安全口径，查库工具在没有"
            "显式允许表集合时一律拒绝执行，不知道该查哪些表就不猜")
    if table not in allow:
        raise BridgeError(
            "TABLE_NOT_ALLOWED",
            "边表 %s 不在 PGROUTING_ALLOWED_TABLES 允许集合内（当前允许：%s）"
            % (table, ", ".join(sorted(allow))))
    return table


def validate_node_id(value, field):
    if isinstance(value, bool):
        raise BridgeError("BAD_NODE_ID", "%s 必须是整数节点 id" % field)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and NODE_ID_RE.match(value.strip()):
        return int(value.strip())
    raise BridgeError(
        "BAD_NODE_ID", "%s 必须是整数节点 id，收到 %r" % (field, value))


def validate_directed(value):
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    raise BridgeError("BAD_DIRECTED", "directed 必须是布尔值，收到 %r" % (value,))


def validate_filename(filename):
    if not isinstance(filename, str) or not filename:
        raise BridgeError("BAD_FILENAME", "filename 必填（只给文件名，不带目录）")
    if os.path.basename(filename) != filename or "/" in filename or \
            "\\" in filename:
        raise BridgeError(
            "BAD_FILENAME", "filename 只能是文件名本身，不许带路径分隔符：%r"
            % (filename,))
    if not FILENAME_RE.match(filename) or filename.startswith("."):
        raise BridgeError(
            "BAD_FILENAME", "filename 只允许 [A-Za-z0-9._-] 且不以点开头：%r"
            % (filename,))
    if not filename.lower().endswith(".geojson"):
        raise BridgeError(
            "BAD_FILENAME", "filename 必须以 .geojson 结尾：%r" % (filename,))
    return filename


def resolve_export_path(filename, output_dir=None):
    """解析导出落点。PGROUTING_EXPORT_DIR 设置后，output_dir 必须落在其内。"""
    name = validate_filename(filename)
    base_env = os.environ.get("PGROUTING_EXPORT_DIR") or None
    if output_dir:
        target_dir = os.path.abspath(output_dir)
        if base_env:
            base_real = os.path.realpath(base_env)
            if os.path.commonpath([base_real,
                                    os.path.realpath(target_dir)]) != base_real:
                raise BridgeError(
                    "EXPORT_DIR_NOT_ALLOWED",
                    "output_dir 必须在 PGROUTING_EXPORT_DIR（%s）之内"
                    % base_env)
    elif base_env:
        target_dir = os.path.abspath(base_env)
    else:
        target_dir = os.path.join(os.getcwd(), "exports")
    return os.path.join(target_dir, name)


# ------------------------------------------------------------- SQL 模板
# 说明：{table} 占位符只会被 validate_table 通过的标识符替换（字符集已被
# 正则锁死，且必须在允许集合内）；:start_id / :end_id / :directed 是 psql
# 变量，值由 Python 侧强转后的 int / bool 生成，调用方原文不进入 SQL。
_ROUTE_INNER = ("SELECT id, source, target, cost, reverse_cost FROM {table}")

ROUTE_SQL = (
    "SELECT seq, node, edge, cost, agg_cost FROM pgr_dijkstra("
    "'" + _ROUTE_INNER + "', :start_id, :end_id, :directed"
    ") ORDER BY seq;"
)

ROUTE_GEOJSON_SQL = (
    "SELECT json_build_object('type', 'FeatureCollection', 'features', "
    "COALESCE(json_agg(f), '[]'::json)) FROM ("
    "SELECT json_build_object('type', 'Feature', "
    "'geometry', ST_AsGeoJSON(e.geom)::json, "
    "'properties', json_build_object('seq', d.seq, 'node', d.node, "
    "'edge', d.edge, 'cost', d.cost, 'agg_cost', d.agg_cost)) AS f "
    "FROM pgr_dijkstra('" + _ROUTE_INNER + "', :start_id, :end_id, "
    ":directed) d "
    "JOIN {table} e ON e.id = d.edge WHERE d.edge <> -1 ORDER BY d.seq) s;"
)

SUMMARY_SQL = (
    "SELECT (SELECT count(*) FROM (SELECT source FROM {table} "
    "UNION SELECT target FROM {table}) AS n) AS node_count, "
    "(SELECT count(*) FROM {table}) AS edge_count;"
)


def render_sql(template, table):
    return template.replace("{table}", table)


# ------------------------------------------------------------- psql 执行
def run_psql(sql, variables=None):
    """以参数数组调用 psql 执行一条固定模板 SQL，返回 stdout 文本。

    连接参数全部由 psql 从 PG* 环境变量继承，本函数不组装连接字符串、
    不接触密码。失败抛 BridgeError，带 psql 的 stderr 原文摘录（截断）。
    """
    exe = psql_path()
    argv = [exe, "-X", "-q", "-v", "ON_ERROR_STOP=1",
            "-A", "-t", "-F", "\t"]
    for key in sorted((variables or {}).keys()):
        argv += ["-v", "%s=%s" % (key, variables[key])]
    argv += ["-c", sql]
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              timeout=psql_timeout())
    except FileNotFoundError:
        raise BridgeError(
            "PSQL_NOT_AVAILABLE",
            "找不到 psql 可执行文件（%s）：请安装 PostgreSQL 客户端，"
            "或用 PGROUTING_PSQL 指定路径" % exe)
    except subprocess.TimeoutExpired:
        raise BridgeError(
            "PSQL_TIMEOUT", "psql 调用超时（%d 秒）" % psql_timeout())
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise BridgeError(
            "PSQL_FAILED", "psql 报错（exit %d）：%s"
            % (proc.returncode, err[:500]))
    return out


def route_variables(start_id, end_id, directed):
    return {"start_id": str(start_id), "end_id": str(end_id),
            "directed": "true" if directed else "false"}


def parse_route_rows(text):
    rows = []
    for line in (text or "").splitlines():
        line = line.strip("\r\n")
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        seq, node, edge, cost, agg_cost = parts
        rows.append({"seq": int(seq), "node": int(node), "edge": int(edge),
                     "cost": float(cost), "agg_cost": float(agg_cost)})
    return rows


def parse_summary(text):
    for line in (text or "").splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 2:
            return {"node_count": int(parts[0]), "edge_count": int(parts[1])}
    raise BridgeError("PSQL_BAD_OUTPUT", "边表统计输出无法解析：%r" % (text[:200],))
