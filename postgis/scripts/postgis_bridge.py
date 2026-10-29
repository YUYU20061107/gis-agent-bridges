# -*- coding: utf-8 -*-
"""
postgis_bridge.py — PostGIS 消费侧只读桥的连接 / 校验 / SQL 模板库
（纯标准库，供 live/mcp_server.py 与 scripts/probe_api.py 共用）

定位：本库是消费侧工具箱——数据与空间函数都在你自己的 PostgreSQL +
PostGIS 里，本库只负责用固定的参数化查询模板把表结构、计数、范围
取出来，或把样本要素落成 GeoJSON 文件。它不提供任何任意 SQL 执行
能力：

  * SQL 只有六条固定模板（版本 / SELECT 1 探针 / 几何列清单 / 属性
    列清单 / 行数 / 范围 Extent / 样本要素 GeoJSON），模板文本写死
    在本文件里，调用方没有任何入口能改动它；
  * 表名只能以标识符形式进入模板，进入前必须同时通过两道校验：
    (1) 正则 ^[A-Za-z0-9_]+$（从字符集上排除引号、分号、空格等一切
        注入材料）；
    (2) 必须在环境变量 POSTGIS_ALLOWED_TABLES 配置的允许集合内；
    集合未配置时一切查库工具直接以 NOT_CONFIGURED 拒绝，不猜默认表；
  * 几何列名同样只许标识符，且必须先经 geometry_columns 清单核对
    确实属于该表，才会被放进 Extent / 导出模板；
  * 表名以外的标量（表名绑定、导出条数上限）都以 psql 变量传入，
    值由 Python 侧强转后生成，调用方原文不拼进 SQL；
  * 数据库访问一律走 psql 子进程的参数数组（subprocess list 形式），
    不经过 shell，不拼连接字符串；
  * 连接参数只从 libpq 标准环境变量读（PGHOST/PGPORT/PGDATABASE/
    PGUSER/PGPASSWORD），由 psql 进程自行从环境继承；本库不读取、
    不记录 PGPASSWORD 的值，日志与回报里最多出现“已设置/未设置”。

表结构约定：目标表位于 public schema（geometry_columns 视图按
f_table_name 匹配）；导出依赖 ST_AsGeoJSON 与 to_jsonb（PostgreSQL
9.5+）。表结构不符时 psql 如实报错，桥原样回传，不猜不凑。

环境变量：
  POSTGIS_PSQL            psql 可执行文件路径（默认 "psql"，走 PATH）
  POSTGIS_ALLOWED_TABLES  允许查询的表名，逗号分隔（查库工具必填）
  POSTGIS_EXPORT_DIR      导出根目录（可选；设置后 output_dir 必须在其内）
  POSTGIS_PSQL_TIMEOUT    单次 psql 调用超时秒数（默认 30）
"""
import os
import re
import shutil
import subprocess

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

MAX_EXPORT_LIMIT = 1000      # 导出要素条数硬上限（改动须同步文档与自检）
DEFAULT_EXPORT_LIMIT = 100   # 导出缺省条数


class BridgeError(Exception):
    """带结构化错误码的桥内错误；mcp_server 会原样转成工具错误回报。"""

    def __init__(self, error_code, message):
        Exception.__init__(self, message)
        self.error_code = error_code
        self.message = message


# ------------------------------------------------------------------ 配置
def psql_path():
    return os.environ.get("POSTGIS_PSQL") or "psql"


def psql_available():
    p = psql_path()
    if os.path.sep in p or (os.path.altsep and os.path.altsep in p):
        return os.path.isfile(p)
    return shutil.which(p) is not None


def allowed_tables():
    raw = os.environ.get("POSTGIS_ALLOWED_TABLES") or ""
    return set(t.strip() for t in raw.split(",") if t.strip())


def psql_timeout():
    try:
        return max(1, int(os.environ.get("POSTGIS_PSQL_TIMEOUT") or 30))
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
            "表名非法：只允许 [A-Za-z0-9_]+ 的单个标识符，收到 %r" % (table,))
    allow = allowed_tables()
    if not allow:
        raise BridgeError(
            "NOT_CONFIGURED",
            "POSTGIS_ALLOWED_TABLES 未配置：出于安全口径，查库工具在没有"
            "显式允许表集合时一律拒绝执行，不知道该查哪些表就不猜")
    if table not in allow:
        raise BridgeError(
            "TABLE_NOT_ALLOWED",
            "表 %s 不在 POSTGIS_ALLOWED_TABLES 允许集合内（当前允许：%s）"
            % (table, ", ".join(sorted(allow))))
    return table


def validate_geom_name(value):
    """几何列名的字符集校验（归属校验在 resolve_geom 里做）。"""
    if not isinstance(value, str) or not IDENT_RE.match(value or ""):
        raise BridgeError(
            "BAD_GEOM_COLUMN",
            "几何列名非法：只允许 [A-Za-z0-9_]+ 的单个标识符，收到 %r"
            % (value,))
    return value


def validate_limit(value, default, hard_max, name="limit"):
    """导出条数：强转 int，超硬上限直接拒绝，不静默截断。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        # 允许数字字符串，但必须纯整数形态
        if isinstance(value, str) and re.match(r"^\d+$", value.strip()):
            value = int(value.strip())
        else:
            raise BridgeError("BAD_LIMIT", "%s 必须是整数，收到 %r"
                              % (name, value))
    if value < 1 or value > hard_max:
        raise BridgeError(
            "LIMIT_EXCEEDED",
            "%s=%d 超出允许范围 1..%d，已拒绝" % (name, value, hard_max))
    return value


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
    """解析导出落点。POSTGIS_EXPORT_DIR 设置后，output_dir 必须落在其内。"""
    name = validate_filename(filename)
    base_env = os.environ.get("POSTGIS_EXPORT_DIR") or None
    if output_dir:
        target_dir = os.path.abspath(output_dir)
        if base_env:
            base_real = os.path.realpath(base_env)
            if os.path.commonpath([base_real,
                                    os.path.realpath(target_dir)]) != base_real:
                raise BridgeError(
                    "EXPORT_DIR_NOT_ALLOWED",
                    "output_dir 必须在 POSTGIS_EXPORT_DIR（%s）之内"
                    % base_env)
    elif base_env:
        target_dir = os.path.abspath(base_env)
    else:
        target_dir = os.path.join(os.getcwd(), "exports")
    return os.path.join(target_dir, name)


# ------------------------------------------------------------- SQL 模板
# 说明：{table} / {geom} 占位符只会被 validate_table / resolve_geom 通过
# 的标识符替换（字符集已被正则锁死，表名还须在允许集合内、几何列还须
# 经 geometry_columns 核对归属）；其余标量（:'tbl' 绑定、:lim 条数）
# 都是 psql 变量，值由 Python 侧强转后生成，调用方原文不进入 SQL。
PROBE_SQL = "SELECT 1;"

VERSION_SQL = "SELECT PostGIS_Version();"

GEOMCOLS_SQL = (
    "SELECT f_geometry_column, type, srid FROM geometry_columns "
    "WHERE f_table_name = :'tbl' ORDER BY f_geometry_column;"
)

COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name = :'tbl' ORDER BY ordinal_position;"
)

COUNT_SQL = "SELECT count(*) FROM {table};"

EXTENT_SQL = (
    "SELECT ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) "
    "FROM (SELECT ST_Extent({geom}) AS b FROM {table}) AS s;"
)

EXPORT_SQL = (
    "SELECT json_build_object('type', 'FeatureCollection', 'features', "
    "COALESCE(json_agg(f), '[]'::json)) FROM ("
    "SELECT json_build_object('type', 'Feature', "
    "'geometry', ST_AsGeoJSON(t.{geom})::json, "
    "'properties', (to_jsonb(t) - '{geom}')) AS f "
    "FROM {table} t LIMIT :lim) s;"
)


def render_sql(template, table=None, geom=None):
    out = template
    if table is not None:
        out = out.replace("{table}", table)
    if geom is not None:
        out = out.replace("{geom}", geom)
    return out


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
            "或用 POSTGIS_PSQL 指定路径" % exe)
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


# ------------------------------------------------------------- 结果解析
def geom_columns(table):
    """查某表在 geometry_columns 里登记的几何列（固定模板＋绑定变量）。"""
    out = run_psql(GEOMCOLS_SQL, {"tbl": table})
    cols = []
    for line in (out or "").splitlines():
        parts = line.strip("\r\n").split("\t")
        if len(parts) != 3:
            continue
        try:
            srid = int(parts[2])
        except Exception:
            srid = None
        cols.append({"column": parts[0], "type": parts[1], "srid": srid})
    return cols


def resolve_geom(table, geom_arg):
    """确定要用的几何列：显式传参须经字符集＋归属双校验；未传时仅当
    该表恰有一个几何列才自动采用，零个/多个都如实报错，不猜。"""
    cols = geom_columns(table)
    names = [c["column"] for c in cols]
    if geom_arg is not None:
        validate_geom_name(geom_arg)
        if geom_arg not in names:
            raise BridgeError(
                "GEOM_NOT_FOUND",
                "表 %s 的 geometry_columns 里没有几何列 %r（现有：%s）"
                % (table, geom_arg, ", ".join(names) or "无"))
        return geom_arg
    if len(names) == 1:
        return names[0]
    if not names:
        raise BridgeError(
            "GEOM_NOT_FOUND",
            "表 %s 在 geometry_columns 里没有登记任何几何列" % table)
    raise BridgeError(
        "AMBIGUOUS_GEOM",
        "表 %s 有多个几何列（%s），请用 geom 参数显式指定"
        % (table, ", ".join(names)))


def parse_columns(text):
    cols = []
    for line in (text or "").splitlines():
        parts = line.strip("\r\n").split("\t")
        if len(parts) != 2:
            continue
        cols.append({"name": parts[0], "data_type": parts[1]})
    return cols


def parse_count(text):
    for line in (text or "").splitlines():
        s = line.strip()
        if s:
            return int(s)
    raise BridgeError("PSQL_BAD_OUTPUT", "行数输出无法解析：%r" % (text[:200],))


def parse_extent(text):
    """ST_Extent 为空集时聚合结果为 NULL，psql 输出空行 -> 返回 None。"""
    for line in (text or "").splitlines():
        parts = line.strip("\r\n").split("\t")
        if len(parts) == 4 and all(p.strip() for p in parts):
            vals = [float(p) for p in parts]
            return {"xmin": vals[0], "ymin": vals[1],
                    "xmax": vals[2], "ymax": vals[3]}
    return None
