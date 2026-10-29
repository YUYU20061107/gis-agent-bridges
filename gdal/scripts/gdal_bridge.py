# -*- coding: utf-8 -*-
"""
gdal_bridge.py — GDAL/OGR 工具桥的校验与调用层（纯标准库）

被 live/mcp_server.py 与 scripts/probe_api.py 共用。设计
口径（与本仓 pgrouting / grass-gis 一致）：

  * 四件工具只经固定调用模板触达：gdalinfo -json（信息）、
    gdalinfo -stats -json（统计）、ogrinfo -so -al（矢量
    图层）、gdal_translate（栅格转换）、ogr2ogr（矢量
    转换）。工具参数里没有、也不接受任何原始 GDAL 选项
    串：没有 -co 透传、没有任意参数拼接。
  * 输入只许本地文件路径：拒绝 /vsi* 虚拟路径与 http(s)
    远程路径（本桥不做网络数据集探查）；路径不存在直接
    PATH_NOT_FOUND，不调用任何二进制。
  * 所有子进程的环境都强制 GDAL_PAM_ENABLED=NO：防止
    gdalinfo -stats 等只读探查在原件旁边写下 .aux.xml
    伴生文件——“只读探查”必须对原件零副作用。
  * 转换只写新文件：输出必须尚不存在、扩展名须与目标
    格式匹配、父目录必须已存在；绝不覆盖任何已有文件。
  * 二进制路径可用环境变量覆盖（GDAL_BRIDGE_GDALINFO 等），
    供自检注入替身与非标准安装使用；缺失时如实报告
    NOT_AVAILABLE，不假装执行过。
"""
import json
import os
import re
import shutil
import subprocess

APP_DIRNAME = ".gdal-agent-bridge"
DEFAULT_TIMEOUT_S = 60

RASTER_FORMATS = {"GTiff": ".tif", "PNG": ".png", "JPEG": ".jpg"}
# GTiff 另接受 .tiff
RASTER_FORMAT_EXTS = {"GTiff": (".tif", ".tiff"), "PNG": (".png",),
                      "JPEG": (".jpg", ".jpeg")}
VECTOR_FORMATS = {"GeoJSON": ".geojson", "GPKG": ".gpkg"}
VECTOR_FORMAT_EXTS = {"GeoJSON": (".geojson", ".json"),
                      "GPKG": (".gpkg",)}
MAX_PATH_CHARS = 1024
MAX_WKT_CHARS = 400


class BridgeError(Exception):
    def __init__(self, error_code, message):
        super().__init__(message)
        self.error_code = error_code
        self.message = message

    def to_dict(self):
        return {"ok": False, "error_code": self.error_code,
                "message": self.message}


def _bin(name, env_key):
    override = (os.environ.get(env_key) or "").strip()
    return override if override else name


def gdalinfo_path():
    return _bin("gdalinfo", "GDAL_BRIDGE_GDALINFO")


def ogrinfo_path():
    return _bin("ogrinfo", "GDAL_BRIDGE_OGRINFO")


def gdal_translate_path():
    return _bin("gdal_translate", "GDAL_BRIDGE_GDAL_TRANSLATE")


def ogr2ogr_path():
    return _bin("ogr2ogr", "GDAL_BRIDGE_OGR2OGR")


def timeout_s():
    try:
        n = int(os.environ.get("GDAL_BRIDGE_TIMEOUT") or DEFAULT_TIMEOUT_S)
    except Exception:
        n = DEFAULT_TIMEOUT_S
    return max(5, min(n, 600))


def _resolved(path):
    found = shutil.which(path)
    if found:
        return found
    if os.path.isfile(path):
        return path
    return None


def tool_available(path):
    return _resolved(path) is not None


def clean_env():
    """子进程环境：强制关 PAM，防只读探查在原件旁写 .aux.xml。"""
    env = dict(os.environ)
    env["GDAL_PAM_ENABLED"] = "NO"
    return env


def _run(path, args, label):
    """以参数数组运行工具，返回 stdout 文本；
    失败统一抛 BridgeError，不返回半成品。"""
    resolved = _resolved(path)
    if not resolved:
        raise BridgeError(
            "NOT_AVAILABLE",
            "%s 不可用：找不到可执行文件 %s" % (label, path))
    try:
        cp = subprocess.run([resolved] + args, capture_output=True,
                            timeout=timeout_s(), env=clean_env())
    except subprocess.TimeoutExpired:
        raise BridgeError("GDAL_TIMEOUT",
                          "%s 超过 %d 秒未完成" % (label, timeout_s()))
    except OSError as e:
        raise BridgeError("NOT_AVAILABLE",
                          "%s 启动失败：%s" % (label, e))
    out = (cp.stdout or b"").decode("utf-8", "replace")
    err = (cp.stderr or b"").decode("utf-8", "replace").strip()
    if cp.returncode != 0:
        raise BridgeError(
            "GDAL_FAILED",
            "%s 退出码 %d：%s" % (label, cp.returncode,
                                  (err or out)[:400]))
    return out


def tool_version(path, label):
    try:
        out = _run(path, ["--version"], label)
        first = out.strip().splitlines()[0] if out.strip() else ""
        return first[:200]
    except BridgeError:
        return None


def validate_input_path(value, field="path"):
    """输入路径：只许本地已存在文件；拒远程与 /vsi 路径。"""
    if not isinstance(value, str) or not value.strip():
        raise BridgeError("BAD_PATH", "%s 必须是非空字符串" % field)
    p = value.strip()
    if len(p) > MAX_PATH_CHARS:
        raise BridgeError("BAD_PATH", "%s 过长" % field)
    low = p.lower()
    if low.startswith("http://") or low.startswith("https://"):
        raise BridgeError(
            "REMOTE_PATH_REJECTED",
            "%s 是远程路径：本桥只探查本地文件，不读网络数据集" % field)
    if low.startswith("/vsi"):
        raise BridgeError(
            "REMOTE_PATH_REJECTED",
            "%s 是 GDAL 虚拟文件系统路径：本桥只探查本地文件" % field)
    if not os.path.isfile(p):
        raise BridgeError("PATH_NOT_FOUND",
                          "%s 不存在或不是文件：%s" % (field, p))
    return p


def validate_output_path(value, format_name, exts):
    """输出路径：必须不存在、扩展名须与格式匹配、父目录须存在。"""
    if not isinstance(value, str) or not value.strip():
        raise BridgeError("BAD_PATH", "output 必须是非空字符串")
    out = value.strip()
    if len(out) > MAX_PATH_CHARS:
        raise BridgeError("BAD_PATH", "output 过长")
    low = out.lower()
    if not any(low.endswith(e) for e in exts):
        raise BridgeError(
            "OUTPUT_EXT_MISMATCH",
            "output 扩展名必须与格式 %s 匹配（%s），收到 %s"
            % (format_name, " / ".join(exts), out))
    if os.path.exists(out):
        raise BridgeError(
            "OUTPUT_EXISTS",
            "输出文件已存在，拒绝覆盖（只写新文件）：%s" % out)
    parent = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(parent):
        raise BridgeError("OUTPUT_PARENT_MISSING",
                          "输出父目录不存在：%s" % parent)
    return out


# ---------------------------------------------------------------- 探查

def raster_info(path):
    raw = _run(gdalinfo_path(), ["-json", path], "gdalinfo")
    try:
        data = json.loads(raw)
    except Exception:
        raise BridgeError(
            "PARSE_FAILED",
            "gdalinfo -json 输出无法解析（老版本 GDAL 可能不支持 "
            "-json），原文前 200 字：%s" % raw[:200])
    cs = data.get("coordinateSystem") or {}
    wkt = cs.get("wkt") or ""
    return {
        "path": path,
        "driver": {"short_name": data.get("driverShortName"),
                   "long_name": data.get("driverLongName")},
        "size": data.get("size"),
        "bands": len(data.get("bands") or []),
        "geo_transform": data.get("geoTransform"),
        "corner_coordinates": data.get("cornerCoordinates"),
        "projection_wkt_head": wkt[:MAX_WKT_CHARS],
        "projection_wkt_truncated": len(wkt) > MAX_WKT_CHARS,
        "pam_disabled": True,
    }


def raster_stats(path):
    raw = _run(gdalinfo_path(), ["-stats", "-json", path], "gdalinfo")
    try:
        data = json.loads(raw)
    except Exception:
        raise BridgeError(
            "PARSE_FAILED",
            "gdalinfo -stats -json 输出无法解析，原文前 200 字：%s"
            % raw[:200])
    bands = []
    for b in data.get("bands") or []:
        bands.append({"band": b.get("band"),
                      "min": b.get("min"), "max": b.get("max"),
                      "mean": b.get("mean"), "std_dev": b.get("stdDev")})
    return {"path": path, "driver_short_name": data.get("driverShortName"),
            "size": data.get("size"), "bands": bands,
            "pam_disabled": True,
            "note": "统计经 GDAL_PAM_ENABLED=NO 计算，不在原件旁写 .aux.xml"}


_LAYER_RE = re.compile(r"^Layer name:\s*(.+)$", re.M)
_GEOM_RE = re.compile(r"^Geometry:\s*(.+)$", re.M)
_COUNT_RE = re.compile(r"^Feature Count:\s*(\d+)", re.M)
_EXTENT_RE = re.compile(
    r"^Extent:\s*\(([-\d.]+),\s*([-\d.]+)\)\s*-\s*\(([-\d.]+),\s*([-\d.]+)\)",
    re.M)
_FIELD_RE = re.compile(
    r"^\s{0,4}([\w ]+?):\s+(String|Integer64|Integer|Real|Date|DateTime|"
    r"Time|Binary)\s*\(", re.M)


def vector_info(path):
    raw = _run(ogrinfo_path(), ["-so", "-al", path], "ogrinfo")
    starts = [m.start() for m in _LAYER_RE.finditer(raw)]
    layers = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(raw)
        block = raw[start:end]
        name = _LAYER_RE.search(block).group(1).strip()
        geom = _GEOM_RE.search(block)
        count = _COUNT_RE.search(block)
        extent = _EXTENT_RE.search(block)
        fields = [m.group(1).strip() for m in _FIELD_RE.finditer(block)]
        layers.append({
            "name": name,
            "geometry": geom.group(1).strip() if geom else None,
            "feature_count": int(count.group(1)) if count else None,
            "extent": ([float(extent.group(j)) for j in range(1, 5)]
                       if extent else None),
            "fields": fields,
        })
    if not layers:
        raise BridgeError(
            "PARSE_FAILED",
            "ogrinfo 输出里没有解析到图层，原文前 200 字：%s" % raw[:200])
    return {"path": path, "layer_count": len(layers), "layers": layers,
            "pam_disabled": True}


# ---------------------------------------------------------------- 转换

def convert_raster(path, output, fmt):
    if fmt not in RASTER_FORMATS:
        raise BridgeError(
            "BAD_FORMAT",
            "format 只许 %s，收到 %r" % (" / ".join(sorted(RASTER_FORMATS)),
                                         fmt))
    src = validate_input_path(path)
    dst = validate_output_path(output, fmt, RASTER_FORMAT_EXTS[fmt])
    _run(gdal_translate_path(), ["-of", fmt, src, dst], "gdal_translate")
    if not os.path.isfile(dst):
        raise BridgeError("CONVERT_NOT_LANDED",
                          "gdal_translate 返回成功但输出文件不存在：%s" % dst)
    return {"ok": True, "input": src, "output": dst, "format": fmt,
            "bytes": os.path.getsize(dst), "executed": True,
            "next_step": "可用 gdal_raster_info 复核输出文件的驱动与尺寸"}


def convert_vector(path, output, fmt):
    if fmt not in VECTOR_FORMATS:
        raise BridgeError(
            "BAD_FORMAT",
            "format 只许 %s，收到 %r" % (" / ".join(sorted(VECTOR_FORMATS)),
                                         fmt))
    src = validate_input_path(path)
    dst = validate_output_path(output, fmt, VECTOR_FORMAT_EXTS[fmt])
    _run(ogr2ogr_path(), ["-f", fmt, dst, src], "ogr2ogr")
    if not os.path.exists(dst):
        raise BridgeError("CONVERT_NOT_LANDED",
                          "ogr2ogr 返回成功但输出不存在：%s" % dst)
    size = os.path.getsize(dst) if os.path.isfile(dst) else None
    return {"ok": True, "input": src, "output": dst, "format": fmt,
            "bytes": size, "executed": True,
            "next_step": "可用 gdal_vector_info 复核输出文件的图层与要素数"}
