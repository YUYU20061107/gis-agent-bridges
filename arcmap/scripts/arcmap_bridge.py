# -*- coding: utf-8 -*-
"""
arcmap_bridge.py — ArcMap 地图文档桥接脚本
版本：v0.3（v0.2 只读基线 + 2026-10-25 实机校准修复 + 受控写动作；由 lab2 魔改版回灌）

子命令：
  preflight   环境预检（定位 ArcMap Desktop 的 Python 与 arcpy，多策略）
  backup      备份 .mxd（时间戳副本 + sha256；同名 .gdb 文件夹一并整体复制）
  inspect     工程盘点：复制到临时目录后打开，枚举数据框/图层/表视图，输出 JSON
  georef      一次多项式（仿射）配准：控制点→系数/残差、world file、可选 Rectify
  mkvector    按 JSON 规格创建 shapefile 并写入要素
  buildmxd    由模板 .mxd 组装地图文档（加图层、设范围）并可选导出 PNG/PDF

设计约束：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - inspect 永不直接打开原件；先复制到临时目录再打开。输出标注
    mode=headless-saved-state。
  - 写动作（georef / mkvector / buildmxd）必须显式 --confirm-write 才落盘，
    且只写到 --out 指定目录；若 out 与源数据目录相同则拒绝执行，保证原件只读。
  - 代码写在 Python 2.7 / 3.x 兼容子集上（ArcMap Desktop 10.x 自带 Python 2.7）。

校准记录（2026-10-25，本机 ArcGIS Desktop 10.8 / Python 2.7.16）：
  - v0.2 的 emit() 在 Python 2 下遇到含中文的 str 会抛
    UnicodeDecodeError: 'ascii' codec can't decode byte 0xef；
    已改为“先递归转 unicode，再 dumps(ensure_ascii=False)，最后写 UTF-8 字节”。
  - 本机 numpy 1.9.3 可用，但配准拟合仍用纯 Python 实现，避免额外依赖。
"""
from __future__ import print_function

import argparse
import glob
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime

try:
    _TEXT = unicode  # noqa: F821  Python 2
except NameError:  # pragma: no cover
    _TEXT = str


# ------------------------------------------------------------------- output
def _dec(b):
    """bytes -> unicode。编码顺序：UTF-8 → 系统文件系统编码（Windows py2 为 mbcs/GBK）→ latin-1。

    Python 2 在 Windows 上 sys.argv 拿到的是 ANSI 代码页字节串（中文系统即 GBK），
    直接按 UTF-8 解码会得到乱码路径，arcpy 就会报 ERROR 000732 Dataset does not exist。
    本函数是这条链路上唯一的解码入口，务必先 utf-8 后 mbcs。
    """
    if isinstance(b, _TEXT):
        return b
    if not isinstance(b, (bytes, bytearray)):
        return u"%s" % b
    try:
        return bytes(b).decode('utf-8')
    except Exception:
        pass
    for enc in (sys.getfilesystemencoding(), 'mbcs', 'gbk', 'latin-1'):
        if not enc:
            continue
        try:
            return bytes(b).decode(enc)
        except Exception:
            continue
    return bytes(b).decode('utf-8', 'replace')


def _to_text(obj):
    """递归把 bytes 解成 unicode，保证 py2 下 json.dumps 不会因混类型崩。"""
    if isinstance(obj, dict):
        return dict((_to_text(k), _to_text(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [_to_text(v) for v in obj]
    if isinstance(obj, _TEXT):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        return _dec(obj)
    return obj


def emit(obj, exit_code=0):
    obj = _to_text(obj)
    try:
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    except Exception:
        try:
            data = json.dumps(obj, ensure_ascii=True).encode('utf-8')
        except Exception:
            data = b'{"ok": false, "error_code": "EMIT_FAILED"}'
    ok = False
    buf = getattr(sys.stdout, 'buffer', None)
    try:
        if buf is not None:          # Python 3
            buf.write(data)
            buf.write(b'\n')
            buf.flush()
        else:                        # Python 2
            sys.stdout.write(data + b'\n')
            sys.stdout.flush()
        ok = True
    except Exception:
        ok = False
    if not ok:
        try:
            sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    return exit_code


def fail(error_code, message, **extra):
    obj = {"ok": False, "error_code": error_code, "message": message}
    obj.update(extra)
    return emit(obj, exit_code=1)


# ---- PathGuard-lite -------------------------------------------------------
# 路径入口校验（main() 分发前统一执行，拒绝时返回 PATH_GUARD_REJECTED）：
#   1) 拒绝 UNC 路径（以双反斜杠或 // 开头）与含 NUL/控制字符的路径；
#   2) 写类参数（_PG_WRITE_ATTRS）的目标路径与任一源路径
#      （_PG_SOURCE_ATTRS 及 layers 列表项）经 realpath+abspath+normcase
#      解析后相同则拒绝，防止把写目标指回原件。其余命令的写目标由脚本
#      按时间戳/固定名派生、不接受调用方指定，不在本条范围。
_PG_SOURCE_ATTRS = ("workspace", "project", "document", "raster", "target",
                    "directory", "image", "points", "spec", "template")
_PG_WRITE_ATTRS = ("out", "export_png")
_PG_LIST_SOURCE_ATTRS = ("layers",)


def _pg_resolve(p):
    try:
        p = _dec(p)
    except Exception:
        pass
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def _pg_check_one(p):
    """单个路径字符串校验，返回违规说明或 None。"""
    if p is None:
        return None
    try:
        s = _dec(p)
    except Exception:
        s = p
    if not isinstance(s, _TEXT):
        s = "%s" % (s,)
    if s.startswith("\\\\") or s.startswith("//"):
        return "UNC 路径不接受: %s" % s
    for ch in s:
        if ord(ch) < 32:
            return "路径含控制字符: %r" % s
    return None


def _path_guard(args):
    """返回违规说明或 None；违规由 main() 以 PATH_GUARD_REJECTED 结构化拒绝。"""
    singles = []
    for attr in _PG_SOURCE_ATTRS + _PG_WRITE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, _TEXT) or isinstance(v, bytes):
            singles.append(v)
    listed = []
    for attr in _PG_LIST_SOURCE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, _TEXT) or isinstance(item, bytes):
                    listed.append(item)
    for v in singles + listed:
        bad = _pg_check_one(v)
        if bad:
            return bad
    sources = []
    for attr in _PG_SOURCE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, _TEXT) or isinstance(v, bytes):
            sources.append(v)
    sources.extend(listed)
    for attr in _PG_WRITE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, _TEXT) or isinstance(v, bytes):
            rv = _pg_resolve(v)
            for s in sources:
                if rv == _pg_resolve(s):
                    return "写目标与源路径相同，拒绝覆盖原件: %s" % v
    return None


def _safe_str(v):
    if v is None:
        return None
    try:
        if isinstance(v, (bytes, bytearray)):
            return v.decode('utf-8', 'replace')
        return u"%s" % v
    except Exception:
        return None


def _u(path):
    """arcpy 更愿意吃 unicode 路径；解码统一走 _dec()，避免 GBK 被当 UTF-8。"""
    return _dec(path)


# ---------------------------------------------------------------- preflight
_PY_PATTERNS = [
    r"C:\Python27\ArcGIS10.*\python.exe",
    r"C:\Python27\ArcGISx6410.*\python.exe",
    r"C:\Python27\ArcGIS10.*\pythonw.exe",
]
_DESKTOP_PATTERNS = [
    r"C:\Program Files (x86)\ArcGIS\Desktop10.*",
    r"C:\Program Files\ArcGIS\Desktop10.*",
]


def _glob_all(patterns):
    found = []
    for pat in patterns:
        try:
            for hit in sorted(glob.glob(pat)):
                if hit not in found:
                    found.append(hit)
        except Exception:
            pass
    return found


def _registry_desktop_dirs():
    dirs = []
    try:
        try:
            import winreg as reg
        except ImportError:
            import _winreg as reg  # noqa: F401
    except Exception:
        return dirs
    for base in (r"SOFTWARE\ESRI", r"SOFTWARE\Wow6432Node\ESRI"):
        try:
            key = reg.OpenKey(reg.HKEY_LOCAL_MACHINE, base)
        except Exception:
            continue
        try:
            i = 0
            while True:
                try:
                    sub = reg.EnumKey(key, i)
                except Exception:
                    break
                i += 1
                if not sub.startswith("Desktop10"):
                    continue
                try:
                    sk = reg.OpenKey(key, sub)
                    val, _t = reg.QueryValueEx(sk, "InstallDir")
                    if val and val not in dirs:
                        dirs.append(val)
                except Exception:
                    continue
        finally:
            try:
                reg.CloseKey(key)
            except Exception:
                pass
    return dirs


def cmd_preflight(args):
    report = {"ok": True, "action": "preflight", "bridge_version": "v0.3",
              "python": sys.version.split()[0],
              "python_executable": sys.executable,
              "checks": {}}
    candidates = _glob_all(_PY_PATTERNS)
    report["candidate_pythons"] = candidates
    desktop_dirs = _glob_all(_DESKTOP_PATTERNS)
    for d in _registry_desktop_dirs():
        if d not in desktop_dirs:
            desktop_dirs.append(d)
    report["desktop_dirs"] = desktop_dirs
    try:
        import arcpy
        report["checks"]["arcpy_import"] = "ok"
        report["arcpy_file"] = _safe_str(getattr(arcpy, "__file__", "unknown"))
        try:
            info = arcpy.GetInstallInfo()
            report["arcgis_product"] = _safe_str(info.get("ProductName"))
            report["arcgis_version"] = _safe_str(info.get("Version"))
            report["arcgis_install_dir"] = _safe_str(info.get("InstallDir"))
        except Exception as e:
            report["checks"]["install_info"] = "fail: %s" % e
    except Exception as e:
        report["checks"]["arcpy_import"] = "fail"
        return fail("ARCPY_NOT_AVAILABLE",
                    "当前解释器无法导入 arcpy: %s；请改用 Desktop 自带 Python 重跑"
                    "（候选路径见 candidate_pythons）" % e, report=report)
    if sys.version_info[0] == 2:
        report["checks"]["runtime_note"] = "Python 2.x，与 ArcMap Desktop 10.x 基线一致"
    else:
        report["checks"]["runtime_note"] = ("当前为 Python 3：arcpy 可导入说明这是 "
                                           "ArcGIS Pro / 独立 arcpy 环境，不是 ArcMap Desktop")
    tools = {}
    for name in ("Warp_management", "CreateFeatureclass_management", "DefineProjection_management",
                 "CopyRaster_management", "AddField_management"):
        tools[name] = hasattr(arcpy, name)
    report["arcpy_tools"] = tools
    report["checks"]["arcpy_mapping"] = hasattr(arcpy, "mapping")
    return emit(report)


# ------------------------------------------------------------------- backup
def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_stats(root):
    count = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            count += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except Exception:
                pass
    return count, total


def cmd_backup(args):
    src = args.document
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "地图文档不存在: %s" % src)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root, ext = os.path.splitext(src)
    dst = "%s.bak-%s%s" % (root, stamp, ext)
    if os.path.exists(dst):
        return fail("BACKUP_EXISTS", "目标备份已存在，拒绝覆盖: %s" % dst)
    shutil.copy2(src, dst)
    result = {"ok": True, "action": "backup", "source": src, "backup": dst,
              "bytes": os.path.getsize(dst), "sha256": _sha256_of(dst)}
    gdb_src = root + ".gdb"
    if os.path.isdir(gdb_src):
        gdb_dst = "%s.bak-%s.gdb" % (root, stamp)
        if os.path.exists(gdb_dst):
            return fail("BACKUP_EXISTS", "目标 GDB 备份已存在，拒绝覆盖: %s" % gdb_dst)
        shutil.copytree(gdb_src, gdb_dst)
        cnt, total = _tree_stats(gdb_dst)
        result["gdb_source"] = gdb_src
        result["gdb_backup"] = gdb_dst
        result["gdb_files"] = cnt
        result["gdb_bytes"] = total
    return emit(result)


# ------------------------------------------------------------------ inspect
def _extent_dict(df):
    try:
        ext = df.extent
        return {"xmin": ext.XMin, "ymin": ext.YMin,
                "xmax": ext.XMax, "ymax": ext.YMax}
    except Exception:
        return None


def _layer_entry(ly):
    entry = {"name": _safe_str(getattr(ly, "name", None))}
    for attr, key in (("dataSource", "data_source"), ("visible", "visible"),
                      ("isBroken", "is_broken"), ("isGroupLayer", "is_group_layer"),
                      ("isFeatureLayer", "is_feature_layer")):
        try:
            entry[key] = getattr(ly, attr)
        except Exception:
            entry[key] = None
    if entry.get("data_source") is not None:
        entry["data_source"] = _safe_str(entry["data_source"])
    return entry


def cmd_inspect(args):
    src = args.document
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "地图文档不存在: %s" % src)
    try:
        import arcpy  # noqa: F401
    except Exception as e:
        return fail("ARCPY_NOT_AVAILABLE", "arcpy 导入失败: %s；请用 Desktop 自带 Python 运行" % e)
    notes = []
    tmpdir = tempfile.mkdtemp(prefix="arcmapbridge-")
    work_copy = os.path.join(tmpdir, os.path.basename(src))
    shutil.copy2(src, work_copy)
    stem = os.path.splitext(src)[0]
    gdb_src = stem + ".gdb"
    gdb_copied = False
    if os.path.isdir(gdb_src):
        try:
            shutil.copytree(gdb_src, os.path.join(tmpdir, os.path.basename(gdb_src)))
            gdb_copied = True
        except Exception as e:
            notes.append("sibling .gdb copy failed: %s" % e)
    mxd = None
    try:
        import arcpy
        mxd = arcpy.mapping.MapDocument(work_copy)
        result = {"ok": True, "action": "inspect", "source": src,
                  "mode": "headless-saved-state",
                  "opened_via": "arcpy.mapping.MapDocument(path)",
                  "gdb_copied": gdb_copied, "notes": notes}
        doc = {}
        doc["file_path"] = _safe_str(getattr(mxd, "filePath", None))
        doc["active_view"] = _safe_str(getattr(mxd, "activeView", None))
        try:
            ps = mxd.pageSize
            doc["page_size"] = {"width": ps.width, "height": ps.height}
        except Exception:
            doc["page_size"] = None
        result["document"] = doc
        frames = []
        total_layers = 0
        for df in arcpy.mapping.ListDataFrames(mxd):
            fentry = {"name": _safe_str(getattr(df, "name", None)), "extent": _extent_dict(df)}
            try:
                fentry["scale"] = df.scale
            except Exception:
                fentry["scale"] = None
            try:
                sr = df.spatialReference
                fentry["spatial_reference"] = _safe_str(getattr(sr, "name", None)) if sr else None
            except Exception:
                fentry["spatial_reference"] = None
            layers = []
            for ly in arcpy.mapping.ListLayers(mxd, "", df):
                layers.append(_layer_entry(ly))
            fentry["layers"] = layers
            total_layers += len(layers)
            frames.append(fentry)
        result["data_frames"] = frames
        result["layer_count"] = total_layers
        tables = []
        try:
            for tv in arcpy.mapping.ListTableViews(mxd):
                tentry = {"name": _safe_str(getattr(tv, "name", None))}
                try:
                    tentry["data_source"] = _safe_str(tv.dataSource)
                except Exception:
                    tentry["data_source"] = None
                tables.append(tentry)
        except Exception as e:
            notes.append("ListTableViews failed: %s" % e)
        result["table_views"] = tables
        result["notes"] = notes
        return emit(result)
    except Exception as e:
        return fail("INSPECT_FAILED", "盘点失败: %s" % e, notes=notes,
                    traceback_tail=traceback.format_exc()[-500:])
    finally:
        if mxd is not None:
            try:
                del mxd
            except Exception:
                pass
        shutil.rmtree(tmpdir, ignore_errors=True)


# -------------------------------------------------------------- georef core
def _solve3(m, v):
    """3x3 线性方程组高斯消元。"""
    a = [list(m[i]) + [v[i]] for i in range(3)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-14:
            raise ValueError("控制点退化，无法求解（是否共线？）")
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col]
        a[col] = [x / pv for x in a[col]]
        for r in range(3):
            if r == col:
                continue
            f = a[r][col]
            a[r] = [a[r][c] - f * a[col][c] for c in range(4)]
    return [a[0][3], a[1][3], a[2][3]]


def fit_affine(pairs):
    """pairs: [(col, row, mapx, mapy)] -> 系数与残差。纯 Python，无 numpy 依赖。"""
    if len(pairs) < 3:
        raise ValueError("控制点少于 3 个，无法做一次多项式拟合")
    n = len(pairs)
    s1 = float(n)
    sc = sum(p[0] for p in pairs)
    sr = sum(p[1] for p in pairs)
    scc = sum(p[0] * p[0] for p in pairs)
    srr = sum(p[1] * p[1] for p in pairs)
    scr = sum(p[0] * p[1] for p in pairs)
    normal = [[s1, sc, sr], [sc, scc, scr], [sr, scr, srr]]
    bx = [sum(p[2] for p in pairs), sum(p[0] * p[2] for p in pairs), sum(p[1] * p[2] for p in pairs)]
    by = [sum(p[3] for p in pairs), sum(p[0] * p[3] for p in pairs), sum(p[1] * p[3] for p in pairs)]
    ax = _solve3(normal, bx)
    ay = _solve3(normal, by)
    residuals = []
    for (col, row, mx, my) in pairs:
        px = ax[0] + ax[1] * col + ax[2] * row
        py = ay[0] + ay[1] * col + ay[2] * row
        residuals.append({"col": col, "row": row,
                          "dmap_x": px - mx, "dmap_y": py - my})
    return ax, ay, residuals


def _metres_per_degree(lat):
    return (111320.0, 111320.0 * math.cos(math.radians(lat)))


def cmd_georef(args):
    try:
        import arcpy
    except Exception as e:
        return fail("ARCPY_NOT_AVAILABLE", "arcpy 导入失败: %s" % e, )
    img = args.image
    if not os.path.isfile(img):
        return fail("FILE_NOT_FOUND", "影像不存在: %s" % img)
    try:
        with io.open(args.points, 'r', encoding='utf-8') as f:
            spec = json.load(f)
        pts = spec['pairs']
        pairs = [(float(p['pixel'][0]), float(p['pixel'][1]),
                  float(p['map'][0]), float(p['map'][1])) for p in pts]
    except Exception as e:
        return fail("POINTS_INVALID", "控制点文件无法解析: %s" % e)

    ax, ay, residuals = fit_affine(pairs)
    lat0 = sum(p[3] for p in pairs) / len(pairs)
    m_lat, m_lon = _metres_per_degree(lat0)
    stat = []
    for r in residuals:
        dx = r['dmap_x'] * m_lon
        dy = r['dmap_y'] * m_lat
        d = math.hypot(dx, dy)
        r['error_m'] = round(d, 4)
        stat.append(d)
    rms = math.sqrt(sum(d * d for d in stat) / len(stat))
    result = {"ok": True, "action": "georef", "bridge_version": "v0.3",
              "image": img, "control_points": len(pairs),
              "transform": "1st order polynomial (affine)",
              "coef_x": {"a0": ax[0], "a1": ax[1], "a2": ax[2]},
              "coef_y": {"b0": ay[0], "b1": ay[1], "b2": ay[2]},
              "formula": "x = a0 + a1*col + a2*row ; y = b0 + b1*col + b2*row",
              "residuals": residuals,
              "rms_m": round(rms, 4), "max_m": round(max(stat), 4),
              "pixel_size_m": {"x": round(math.hypot(ax[1] * m_lon, ay[1] * m_lat), 4),
                              "y": round(math.hypot(ax[2] * m_lon, ay[2] * m_lat), 4)},
              "notes": []}
    try:
        _cols = arcpy.GetRasterProperties_management(_u(img), "COLUMNCOUNT").getOutput(0)
        _rows = arcpy.GetRasterProperties_management(_u(img), "ROWCOUNT").getOutput(0)
        w, h = int(float(_cols)), int(float(_rows))
    except Exception:
        try:
            from PIL import Image  # noqa: F401
            w, h = Image.open(img).size
        except Exception:
            w = h = None
    result["raster_size_px"] = {"width": w, "height": h}

    if not args.out:
        result["write"] = "skipped: 未指定 --out"
        return emit(result)
    if not args.confirm_write:
        result["write"] = "skipped: 需要 --confirm-write 才落盘"
        return emit(result)

    out_dir = os.path.abspath(args.out)
    if os.path.abspath(os.path.dirname(os.path.abspath(img))) == out_dir:
        return fail("OUT_IS_SOURCE_DIR", "输出目录不能是源影像所在目录（原件只读）")
    try:
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
    except Exception as e:
        return fail("OUT_CREATE_FAILED", "输出目录创建失败: %s" % e)

    base = os.path.splitext(os.path.basename(img))[0]
    written = []

    # 1) world file（Update Georeferencing 等价物）
    wf = [ax[1], ay[1], ax[2], ay[2],
          ax[0] + 0.5 * ax[1] + 0.5 * ax[2],
          ay[0] + 0.5 * ay[1] + 0.5 * ay[2]]
    jgw = os.path.join(out_dir, base + ".jgw")
    with open(jgw, 'wb') as f:
        f.write(("\n".join("%.12f" % v for v in wf) + "\n").encode('ascii'))
    written.append({"file": jgw, "bytes": os.path.getsize(jgw)})

    # 2) 带 georeference 的影像副本 + 定义投影
    geo_img = os.path.join(out_dir, base + "_geo.jpg")
    shutil.copy2(img, geo_img)
    shutil.copy2(jgw, os.path.join(out_dir, base + "_geo.jgw"))
    written.append({"file": geo_img, "bytes": os.path.getsize(geo_img)})
    sr = arcpy.SpatialReference(int(args.sr))
    proj_info = "skipped"
    try:
        arcpy.DefineProjection_management(_u(geo_img), sr)
        proj_info = "ok"
    except Exception as e:
        proj_info = "fail: %s" % e
        result["notes"].append("DefineProjection 失败：%s" % e)

    # 3) 导出 TIFF（保留完整仿射/旋转）
    tif = os.path.join(out_dir, base + "_geo.tif")
    try:
        if os.path.exists(tif):
            os.remove(tif)
        arcpy.CopyRaster_management(_u(geo_img), _u(tif))
        written.append({"file": tif, "bytes": os.path.getsize(tif)})
        try:
            ext = arcpy.Describe(_u(tif)).extent
            result["tif_extent"] = [round(ext.XMin, 8), round(ext.YMin, 8),
                                    round(ext.XMax, 8), round(ext.YMax, 8)]
        except Exception:
            pass
    except Exception as e:
        result["notes"].append("CopyRaster 失败：%s" % e)

    # 4) 可选：校正为北向对齐栅格（等价于 Georeferencing → Rectify 的产物）
    #
    # 校准记录：本机 ArcMap 10.8 的 Warp_management 对文本控制点一律报
    #   ERROR 000735: Source Control Points: Value is required（ASCII 路径、
    #   tab/空格分隔、>=3 点均已排除），故不再使用 Warp。
    #   已验证可行路径：对已写好 world file 并 DefineProjection 的影像调用
    #   ProjectRaster_management(同坐标系)，输出 GeoTIFF 为
    #   33550 ModelPixelScale + 33922 ModelTiepoint（无旋转项）= 真正北向对齐。
    if args.rectify:
        rec_tif = os.path.join(out_dir, base + "_rectify.tif")
        try:
            if os.path.exists(rec_tif):
                os.remove(rec_tif)
            arcpy.ProjectRaster_management(_u(geo_img), _u(rec_tif), sr, "BILINEAR")
            written.append({"file": rec_tif, "bytes": os.path.getsize(rec_tif)})
            try:
                ext = arcpy.Describe(_u(rec_tif)).extent
                result["rectify_extent"] = [round(ext.XMin, 8), round(ext.YMin, 8),
                                            round(ext.XMax, 8), round(ext.YMax, 8)]
                cols = arcpy.GetRasterProperties_management(_u(rec_tif), "COLUMNCOUNT").getOutput(0)
                rows = arcpy.GetRasterProperties_management(_u(rec_tif), "ROWCOUNT").getOutput(0)
                result["rectify_size_px"] = {"width": int(float(cols)), "height": int(float(rows))}
            except Exception:
                pass
        except Exception as e:
            result["notes"].append("ProjectRaster 校正失败：%s" % e)

    result["write"] = "done"
    result["define_projection"] = proj_info
    result["written"] = written
    rp = os.path.join(out_dir, "georef_report.json")
    with io.open(rp, 'w', encoding='utf-8') as f:
        f.write(_TEXT(json.dumps(_to_text(result), ensure_ascii=False, indent=1)))
    return emit(result)


# ------------------------------------------------------------------ mkvector
def cmd_mkvector(args):
    try:
        import arcpy
    except Exception as e:
        return fail("ARCPY_NOT_AVAILABLE", "arcpy 导入失败: %s" % e)
    try:
        with io.open(args.spec, 'r', encoding='utf-8') as f:
            spec = json.load(f)
        layers = spec['layers']
    except Exception as e:
        return fail("SPEC_INVALID", "矢量规格无法解析: %s" % e)
    out_dir = os.path.abspath(args.out)
    if not args.confirm_write:
        return emit({"ok": True, "action": "mkvector", "write": "skipped: 需要 --confirm-write",
                     "out": out_dir, "layers": [l['name'] for l in layers]})
    try:
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
    except Exception as e:
        return fail("OUT_CREATE_FAILED", "输出目录创建失败: %s" % e)
    sr = arcpy.SpatialReference(int(spec.get('spatial_reference', 4326)))
    report = []
    for lay in layers:
        name = lay['name']
        geom = lay.get('geometry', 'POLYGON').upper()
        if geom not in ('POLYGON', 'POLYLINE', 'POINT'):
            return fail("GEOM_INVALID", "不支持的几何类型: %s" % geom)
        path = os.path.join(out_dir, name + ".shp")
        try:
            if os.path.exists(path):
                for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx'):
                    p = os.path.join(out_dir, name + ext)
                    if os.path.exists(p):
                        os.remove(p)
            arcpy.CreateFeatureclass_management(out_dir, name, geom, "", "DISABLED", "DISABLED",
                                                sr)
            fields = lay.get('fields', [])
            for fd in fields:
                arcpy.AddField_management(path, fd['name'], fd.get('type', 'TEXT'),
                                          fd.get('length', 50))
            field_names = ['SHAPE@'] + [f['name'] for f in fields]
            cur = arcpy.da.InsertCursor(path, field_names)
            n = 0
            for ft in lay.get('features', []):
                coords = ft.get('coords', [])
                if geom == 'POINT':
                    g = arcpy.Point(coords[0][0], coords[0][1]) if coords else None
                elif geom == 'POLYLINE':
                    g = arcpy.Polyline(arcpy.Array([arcpy.Point(x, y) for (x, y) in coords]), sr)
                else:
                    pts = list(coords)
                    if pts and (abs(pts[0][0] - pts[-1][0]) > 1e-12 or abs(pts[0][1] - pts[-1][1]) > 1e-12):
                        pts = pts + [pts[0]]
                    g = arcpy.Polygon(arcpy.Array([arcpy.Point(x, y) for (x, y) in pts]), sr)
                attrs = ft.get('attrs', {})
                cur.insertRow([g] + [attrs.get(f['name'], u"") for f in fields])
                n += 1
            del cur
            files = {}
            for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
                p = os.path.join(out_dir, name + ext)
                files[ext] = os.path.getsize(p) if os.path.exists(p) else None
            cnt = int(arcpy.GetCount_management(path).getOutput(0))
            report.append({"layer": name, "geometry": geom, "features_written": n,
                           "features_counted": cnt, "files": files})
        except Exception as e:
            return fail("LAYER_FAILED", "图层 %s 写入失败: %s" % (name, e),
                        traceback_tail=traceback.format_exc()[-600:], done=report)
    return emit({"ok": True, "action": "mkvector", "out": out_dir, "layers": report,
                 "spatial_reference": _safe_str(sr.name)})


# ------------------------------------------------------------------ buildmxd
def cmd_buildmxd(args):
    try:
        import arcpy
    except Exception as e:
        return fail("ARCPY_NOT_AVAILABLE", "arcpy 导入失败: %s" % e)
    if not os.path.isfile(args.template):
        return fail("TEMPLATE_NOT_FOUND", "模板 .mxd 不存在: %s" % args.template)
    layers = [p for p in (args.layers or []) if p]
    for p in layers:
        if not os.path.exists(p):
            return fail("LAYER_NOT_FOUND", "图层不存在: %s" % p)
    out = os.path.abspath(args.out)
    if not args.confirm_write:
        return emit({"ok": True, "action": "buildmxd", "write": "skipped: 需要 --confirm-write",
                     "out": out, "layers": len(layers)})
    out_dir = os.path.dirname(out)
    if out_dir and not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir)
        except Exception as e:
            return fail("OUT_CREATE_FAILED", "输出目录创建失败: %s" % e)
    mxd = None
    try:
        mxd = arcpy.mapping.MapDocument(_u(args.template))
        dfs = arcpy.mapping.ListDataFrames(mxd)
        if not dfs:
            return fail("NO_DATAFRAME", "模板里没有数据框")
        df = dfs[0]
        report = {"ok": True, "action": "buildmxd", "template": args.template,
                  "data_frame": _safe_str(df.name), "added": []}
        for p in layers:
            ly = arcpy.mapping.Layer(_u(p))
            arcpy.mapping.AddLayer(df, ly, "TOP")
            report["added"].append({"layer": _safe_str(ly.name), "source": p,
                                    "is_broken": bool(getattr(ly, "isBroken", False))})
        if args.extent:
            vals = [float(v) for v in args.extent.split(',')]
            df.extent = arcpy.Extent(vals[0], vals[1], vals[2], vals[3])
            report["extent"] = vals
            report["scale"] = df.scale
        if os.path.exists(out):
            os.remove(out)
        mxd.saveACopy(_u(out))
        report["saved"] = {"path": out, "bytes": os.path.getsize(out) if os.path.exists(out) else 0}
        if args.export_png:
            png = os.path.abspath(args.export_png)
            try:
                arcpy.mapping.ExportToPNG(mxd, _u(png), resolution=int(args.dpi))
                report["export_png"] = {"path": png,
                                        "bytes": os.path.getsize(png) if os.path.exists(png) else 0,
                                        "dpi": int(args.dpi)}
            except Exception as e:
                report["export_png"] = {"error": _safe_str(e)}
        return emit(report)
    except Exception as e:
        return fail("BUILD_FAILED", "组装失败: %s" % e, traceback_tail=traceback.format_exc()[-800:])
    finally:
        if mxd is not None:
            try:
                del mxd
            except Exception:
                pass


def main():
    p = argparse.ArgumentParser(prog="arcmap_bridge")
    sub = p.add_subparsers(dest="cmd")
    pp = sub.add_parser("preflight")
    pp.set_defaults(func=cmd_preflight)
    bp = sub.add_parser("backup")
    bp.add_argument("document")
    bp.set_defaults(func=cmd_backup)
    ip = sub.add_parser("inspect")
    ip.add_argument("document")
    ip.set_defaults(func=cmd_inspect)

    gp = sub.add_parser("georef")
    gp.add_argument("--image", required=True)
    gp.add_argument("--points", required=True)
    gp.add_argument("--out")
    gp.add_argument("--sr", default="4326")
    gp.add_argument("--rectify", action="store_true")
    gp.add_argument("--confirm-write", action="store_true")
    gp.set_defaults(func=cmd_georef)

    mp = sub.add_parser("mkvector")
    mp.add_argument("--spec", required=True)
    mp.add_argument("--out", required=True)
    mp.add_argument("--confirm-write", action="store_true")
    mp.set_defaults(func=cmd_mkvector)

    xp = sub.add_parser("buildmxd")
    xp.add_argument("--template", required=True)
    xp.add_argument("--layers", nargs="*", default=[])
    xp.add_argument("--out", required=True)
    xp.add_argument("--extent")
    xp.add_argument("--export-png")
    xp.add_argument("--dpi", default="150")
    xp.add_argument("--confirm-write", action="store_true")
    xp.set_defaults(func=cmd_buildmxd)

    args = p.parse_args()
    if not hasattr(args, "func"):
        p.print_help()
        return 2
    _pg_err = _path_guard(args)
    if _pg_err:
        return fail("PATH_GUARD_REJECTED", _pg_err, error="PATH_GUARD_REJECTED")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
