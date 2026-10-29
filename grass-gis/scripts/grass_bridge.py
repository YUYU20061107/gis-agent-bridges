# -*- coding: utf-8 -*-
"""
grass_bridge.py — GRASS GIS 无头桥的路径 / 校验 / 调用库
（纯标准库，供 live/mcp_server.py 与 scripts/probe_api.py 共用）

定位：本库是无头处理工具箱——GRASS GIS 以批处理形态
（grass <mapset> --exec <模块>）在本机运行，本库只负责把
有限的、模板化的调用拼出来并取回结果。它不提供任意模块
执行能力：

  * 能调的模块只有写死的几条：g.list（列图层）、r.info
    （栅格信息）、v.out.ogr（矢量导出），以及 run 作业枚举
    里的三个固定模板（r.slope.aspect / r.relief /
    r.resample）。模块名与参数名都在代码里固定，调用方只能
    提供经校验的值（图层名、作业名、新图层名、导出路径）；
  * 图层名只许 [A-Za-z0-9_.]（可带一个 @mapset 后缀，两段
    各自校验）；location / mapset 名只许单个路径分量
    （[A-Za-z0-9_.-]，不许 "." ".."），拼出的真实路径必须
    落在 GRASS_BRIDGE_GISDBASE 之内，防路径穿越；
  * GIS 数据库根目录只从环境变量 GRASS_BRIDGE_GISDBASE
    读，工具参数里不接受任何目录路径；
  * 一切子进程调用都走参数数组（subprocess list 形式），
    不经 shell；绝不传 --overwrite：GRASS 对已存在的输出
    图层会自己报错拒绝，桥不替它放行——处理结果只能落成
    新图层，原有图层零改动（副本原则的进程内形态）；
  * 导出只许写新文件：输出文件已存在时在调用 GRASS 之前
    就以 OUTPUT_EXISTS 拒绝；设置了 GRASS_BRIDGE_EXPORT_DIR
    时导出必须落在其内。

环境变量：
  GRASS_BRIDGE_BIN        grass 可执行文件路径（默认 "grass"）
  GRASS_BRIDGE_GISDBASE   GRASS 数据库根目录（业务工具必填）
  GRASS_BRIDGE_EXPORT_DIR 导出根目录（可选）
  GRASS_BRIDGE_TIMEOUT    单次 grass 调用超时秒数（默认 120）
"""
import os
import re
import shutil
import subprocess

COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAP_RE = re.compile(r"^[A-Za-z0-9_.]+$")
FILENAME_EXTS = (".geojson",)

MAP_TYPES = ("raster", "vector", "raster_3d", "region")

# run 作业枚举：作业名 -> (模块, [(参数名, 角色), ...])
# 角色：in=已有图层（可带 @mapset）；out=新图层名（不许带 @）
RUN_JOBS = {
    "slope_aspect": ("r.slope.aspect",
                     [("elevation", "in"), ("slope", "out"),
                      ("aspect", "out")]),
    "hillshade": ("r.relief",
                  [("input", "in"), ("output", "out")]),
    "resample_nearest": ("r.resample",
                         [("input", "in"), ("output", "out")]),
}


class BridgeError(Exception):
    """带结构化错误码的桥内错误；mcp_server 会原样转成工具错误回报。"""

    def __init__(self, error_code, message):
        Exception.__init__(self, message)
        self.error_code = error_code
        self.message = message


# ------------------------------------------------------------------ 配置
def grass_path():
    return os.environ.get("GRASS_BRIDGE_BIN") or "grass"


def grass_available():
    p = grass_path()
    if os.path.sep in p or (os.path.altsep and os.path.altsep in p):
        return os.path.isfile(p)
    return shutil.which(p) is not None


def gisdbase():
    raw = (os.environ.get("GRASS_BRIDGE_GISDBASE") or "").strip()
    return raw or None


def grass_timeout():
    try:
        return max(1, int(os.environ.get("GRASS_BRIDGE_TIMEOUT") or 120))
    except Exception:
        return 120


# ------------------------------------------------------------------ 校验
def validate_component(value, field):
    """location / mapset 名：只许单个路径分量。"""
    if not isinstance(value, str) or not COMPONENT_RE.match(value or ""):
        raise BridgeError(
            "BAD_NAME",
            "%s 非法：只允许 [A-Za-z0-9_.-] 的单个路径分量，收到 %r"
            % (field, value))
    if value in (".", ".."):
        raise BridgeError("BAD_NAME", "%s 不许是 %r" % (field, value))
    return value


def validate_map_name(value, field="map"):
    """图层名：name 或 name@mapset，两段各自只许 [A-Za-z0-9_.]。"""
    if not isinstance(value, str) or not value:
        raise BridgeError("BAD_MAP_NAME", "%s 必填，收到 %r" % (field, value))
    parts = value.split("@")
    if len(parts) > 2:
        raise BridgeError("BAD_MAP_NAME",
                          "%s 最多含一个 @：%r" % (field, value))
    for p in parts:
        if not MAP_RE.match(p):
            raise BridgeError(
                "BAD_MAP_NAME",
                "%s 非法：只允许 [A-Za-z0-9_.]，收到 %r" % (field, value))
    return value


def validate_new_map_name(value, field):
    """输出图层名：不许带 @mapset（只能落在当前 mapset 里）。"""
    validate_map_name(value, field)
    if "@" in value:
        raise BridgeError(
            "BAD_MAP_NAME",
            "%s 是输出图层名，不许带 @mapset：%r" % (field, value))
    return value


def _inside(base, target):
    base_real = os.path.realpath(base)
    return os.path.commonpath([base_real,
                               os.path.realpath(target)]) == base_real


def location_dir(location):
    """解析并核验 location 目录：必须真实存在且落在 gisdbase 内。"""
    base = gisdbase()
    if not base:
        raise BridgeError(
            "NOT_CONFIGURED",
            "GRASS_BRIDGE_GISDBASE 未配置：不知道 GRASS 数据库在哪"
            "就不猜")
    validate_component(location, "location")
    path = os.path.join(base, location)
    if not _inside(base, path):
        raise BridgeError("PATH_NOT_ALLOWED",
                          "location 路径越出 GRASS 数据库根目录")
    if not os.path.isdir(path):
        raise BridgeError("LOCATION_NOT_FOUND",
                          "location 不存在：%s" % path)
    if not os.path.isdir(os.path.join(path, "PERMANENT")):
        raise BridgeError(
            "LOCATION_INVALID",
            "目录 %s 下没有 PERMANENT mapset，不像 GRASS location"
            % path)
    return path


def mapset_dir(location, mapset):
    loc = location_dir(location)
    validate_component(mapset, "mapset")
    path = os.path.join(loc, mapset)
    if not _inside(loc, path):
        raise BridgeError("PATH_NOT_ALLOWED",
                          "mapset 路径越出 location 目录")
    if not os.path.isdir(path):
        raise BridgeError("MAPSET_NOT_FOUND", "mapset 不存在：%s" % path)
    return path


def list_locations():
    """列 gisdbase 下带 PERMANENT 的子目录名（只看目录结构）。"""
    base = gisdbase()
    if not base or not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if os.path.isdir(os.path.join(base, name, "PERMANENT")):
            out.append(name)
    return out


def _parse_key_value_file(path):
    """解析 PROJ_INFO / WIND 一类 'key: value' 文本文件。"""
    data = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip()
    except Exception:
        pass
    return data


def location_info(location):
    loc = location_dir(location)
    permanent = os.path.join(loc, "PERMANENT")
    proj = _parse_key_value_file(os.path.join(permanent, "PROJ_INFO"))
    wind = _parse_key_value_file(os.path.join(permanent, "WIND"))
    mapsets = []
    for name in sorted(os.listdir(loc)):
        if os.path.isdir(os.path.join(loc, name)):
            mapsets.append(name)
    return {"location": location, "path": loc, "mapsets": mapsets,
            "projection": proj, "default_region": wind}


def resolve_export_path(output):
    """导出落点：必须是 .geojson 的新文件；EXPORT_DIR 设置时
    必须落在其内。已存在的文件在调用 GRASS 前就拒绝。"""
    if not isinstance(output, str) or not output:
        raise BridgeError("BAD_OUTPUT", "output 必填（导出文件路径）")
    if not output.lower().endswith(FILENAME_EXTS):
        raise BridgeError("BAD_OUTPUT",
                          "output 必须以 .geojson 结尾：%r" % (output,))
    path = os.path.abspath(output)
    base_env = os.environ.get("GRASS_BRIDGE_EXPORT_DIR") or None
    if base_env and not _inside(base_env, path):
        raise BridgeError(
            "EXPORT_DIR_NOT_ALLOWED",
            "output 必须在 GRASS_BRIDGE_EXPORT_DIR（%s）之内" % base_env)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        raise BridgeError("BAD_OUTPUT",
                          "output 所在目录不存在：%s" % parent)
    if os.path.exists(path):
        raise BridgeError(
            "OUTPUT_EXISTS",
            "输出文件已存在，拒绝覆盖（副本原则：只写新文件）：%s" % path)
    return path


# ------------------------------------------------------------- grass 执行
def run_grass(mapset_path, module_args):
    """以参数数组运行 grass <mapset> --exec <模块与参数>。
    返回 stdout 文本；非零退出抛 GRASS_FAILED 并带 stderr 摘录。"""
    exe = grass_path()
    argv = [exe, mapset_path, "--exec"] + list(module_args)
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              timeout=grass_timeout())
    except FileNotFoundError:
        raise BridgeError(
            "GRASS_NOT_AVAILABLE",
            "找不到 grass 可执行文件（%s）：请安装 GRASS GIS，"
            "或用 GRASS_BRIDGE_BIN 指定路径" % exe)
    except subprocess.TimeoutExpired:
        raise BridgeError("GRASS_TIMEOUT",
                          "grass 调用超时（%d 秒）" % grass_timeout())
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise BridgeError(
            "GRASS_FAILED", "grass 报错（exit %d）：%s"
            % (proc.returncode, err[:500] or out[:500]))
    return out


def grass_version():
    exe = grass_path()
    try:
        proc = subprocess.run([exe, "--version"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=15)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", "replace").strip()
    return text.splitlines()[0] if text else ""


def parse_name_list(text):
    names = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s and not s.startswith("-"):
            names.append(s)
    return names


def parse_key_values(text):
    data = {}
    for line in (text or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def build_run_args(job, params):
    """把 run 作业拼成固定模块的参数数组。job 不在枚举内、
    缺参数、参数角色不符都在这里拒绝，不发出任何调用。"""
    if job not in RUN_JOBS:
        raise BridgeError(
            "BAD_JOB",
            "job 只许 %s，收到 %r" % (" / ".join(sorted(RUN_JOBS)), job))
    module, spec = RUN_JOBS[job]
    if not isinstance(params, dict):
        raise BridgeError("BAD_PARAMS", "params 必须是 JSON 对象")
    argv = [module]
    used = {}
    for pname, role in spec:
        value = params.get(pname)
        if value is None:
            raise BridgeError("MISSING_PARAM",
                              "job %s 缺少参数 %s" % (job, pname))
        if role == "in":
            validate_map_name(value, pname)
        else:
            validate_new_map_name(value, pname)
        used[pname] = value
        argv.append("%s=%s" % (pname, value))
    extra = set(params) - {p for p, _r in spec}
    if extra:
        raise BridgeError(
            "BAD_PARAMS",
            "job %s 不接受这些参数：%s" % (job, ", ".join(sorted(extra))))
    return module, argv, used
