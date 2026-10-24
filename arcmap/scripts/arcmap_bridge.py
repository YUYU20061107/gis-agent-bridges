# -*- coding: utf-8 -*-
"""
arcmap_bridge.py — ArcMap 地图文档（.mxd）无头桥接脚本（v0.1，只读优先）

子命令：
  preflight  环境预检（定位 ArcMap Desktop 的 Python 2.7 与 arcpy，多策略）
  backup     备份 .mxd（时间戳副本 + sha256；同名 .gdb 文件夹一并整体复制）
  inspect    工程盘点：复制到临时目录后打开，枚举数据框/图层/表视图，输出 JSON

设计约束：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - inspect 永不直接打开原件；先复制到临时目录再打开。输出标注
    mode=headless-saved-state：无头打开只能看到文件里已保存的状态，
    看不到 ArcMap 界面里尚未保存的修改，不许冒充实时。
  - 代码写在 Python 2.7 / 3.x 兼容子集上（ArcMap Desktop 10.x 自带
    Python 2.7，如 C:\\Python27\\ArcGIS10.x\\python.exe）。
  - 本脚本不包含任何写业务动作（不 save、不删、不改工程内容）。
"""
from __future__ import print_function

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime


def emit(obj, exit_code=0):
    line = json.dumps(obj, ensure_ascii=False)
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        # 兜底：编码受限的控制台（如 GBK）下退回 ASCII 转义，仍是合法 JSON
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


def _safe_str(v):
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


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
    """从注册表 HKLM\\SOFTWARE\\ESRI 枚举 Desktop10.* 的 InstallDir（尽力而为）。"""
    dirs = []
    try:
        try:
            import winreg as reg
        except ImportError:
            import _winreg as reg  # noqa: F401  Python 2.7 名称
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
    report = {"ok": True, "action": "preflight",
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
        return fail("ARCPY_NOT_AVAILABLE",
                    "arcpy 导入失败: %s；请用 Desktop 自带 Python 运行" % e)
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
            fentry = {"name": _safe_str(getattr(df, "name", None)),
                      "extent": _extent_dict(df)}
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
    args = p.parse_args()
    if not hasattr(args, "func"):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
