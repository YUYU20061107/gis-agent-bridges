#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_project.py —— ArcGIS Pro 工程盘点 / 迁移验收（只读）。

对 .aprx 工程做两层盘点并输出结构化 JSON（顶层带 issues 列表）：

  1) 纯标准库层（不需要 arcpy）：文件存在与大小、.aprx 的 ZIP 结构
     （条目数 / testzip 完整性）、同目录 shapefile 伴生文件完整性
     （.shp 必须有 .shx/.dbf，.prj/.cpg 缺失记为 issue）、同名 .gdb
     文件夹是否存在。
  2) arcpy 层：把工程复制到临时目录（同名 .gdb 一并复制，原件零接触）
     后用 arcpy.mp 打开，枚举地图 / 图层 / 独立表 / 布局，断裂图层、
     无地图等记入 issues。当前解释器没有 arcpy 时不抛 traceback，
     输出 {"ok": false, "error": "ARCPY_NOT_AVAILABLE", ...} 并以
     退出码 1 结束（纯标准库层的结果仍包含在同一份 JSON 里）。

--copy-to <dir>：先把工程文件 + 同主名伴生文件（同名 .gdb 文件夹整体、
同主名的 .shp/.shx/.dbf/.prj/.cpg/.sbn/.sbx/.shp.xml 等）复制到目标目录，
再对副本重新盘点，用于验收"换目录后还能不能打开、数据源全不全"。
目标目录已存在时以结构化 JSON 报错退出，绝不覆盖。

用法：
  python verify_project.py --project <工程.aprx>
  python verify_project.py <工程.aprx> --copy-to <新目录> [--json-out out.json]

注意：本脚本是无头盘点，只能看到工程上次保存到磁盘的状态，
看不到 ArcGIS Pro 界面里的未保存修改；结论口径与 scripts/arcgis_bridge.py 的
inspect 一致。
"""
import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

# stdout 锁定 UTF-8：中文 Windows 管道默认 GBK 编码会让含中文/生僻字的
# JSON 输出乱码或 UnicodeEncodeError 崩溃（与各包无头桥同口径）。
if getattr(sys.stdout, "encoding", None) != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
    except Exception:
        pass


COMPANION_EXTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx",
                  ".shp.xml", ".xml", ".atx", ".aih", ".ain")
REQUIRED_SHP_COMPANIONS = (".shx", ".dbf")
OPTIONAL_SHP_COMPANIONS = (".prj", ".cpg")


def _emit(out, code, json_out=None):
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if json_out:
        with io.open(json_out, "w", encoding="utf-8") as f:
            f.write(text)
    return code


def _safe_str(v):
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _try_attrs(obj, names):
    for name in names:
        if obj is None:
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        try:
            if callable(val):
                val = val()
            return val, name
        except Exception:
            continue
    return None, None


def _to_list(coll):
    if coll is None:
        return []
    try:
        return list(coll)
    except Exception:
        pass
    try:
        return [coll[i] for i in range(len(coll))]
    except Exception:
        return []


def pure_python_inventory(project, issues):
    """不依赖 arcpy 的盘点：文件、ZIP 结构、伴生文件完整性。"""
    info = {"path": os.path.abspath(project),
            "bytes": os.path.getsize(project)}
    stem, ext = os.path.splitext(project)
    if ext.lower() != ".aprx":
        issues.append("工程扩展名不是 .aprx：%s" % ext)
    # .aprx 本质是 ZIP 包：校验结构与条目
    if zipfile.is_zipfile(project):
        info["is_zip"] = True
        try:
            with zipfile.ZipFile(project) as zf:
                names = zf.namelist()
                info["zip_entries"] = len(names)
                info["zip_bad_entry"] = zf.testzip()
                if info["zip_bad_entry"]:
                    issues.append("ZIP 结构损坏，坏条目：%s" % info["zip_bad_entry"])
        except Exception as exc:
            info["zip_error"] = str(exc)
            issues.append("ZIP 读取失败：%s" % exc)
    else:
        info["is_zip"] = False
        issues.append("文件不是 ZIP 结构（.aprx 应为 ZIP 包，可能已损坏或格式异常）")
    proj_dir = os.path.dirname(os.path.abspath(project))
    gdb_dir = stem + ".gdb"
    info["sibling_gdb_exists"] = os.path.isdir(gdb_dir)
    # 同目录全部 shapefile 的伴生完整性（含工程同主名与其他 shp）
    shp_report = []
    try:
        entries = sorted(os.listdir(proj_dir))
    except Exception:
        entries = []
    lower_map = {}
    for fn in entries:
        lower_map.setdefault(fn.lower(), fn)
    for fn in entries:
        if not fn.lower().endswith(".shp"):
            continue
        base = fn[:-4]
        entry = {"shp": fn}
        for req in REQUIRED_SHP_COMPANIONS:
            present = (base.lower() + req) in lower_map
            entry[req.lstrip(".")] = present
            if not present:
                issues.append("shapefile %s 缺少必需伴生文件 %s%s" % (fn, base, req))
        for opt in OPTIONAL_SHP_COMPANIONS:
            entry[opt.lstrip(".")] = (base.lower() + opt) in lower_map
        shp_report.append(entry)
    info["shapefiles_in_project_dir"] = shp_report
    return info


def copy_project_tree(project, dest):
    """复制工程文件 + 同主名伴生文件到 dest（dest 须不存在，调用方已校验）。"""
    src_dir = os.path.dirname(os.path.abspath(project))
    base = os.path.basename(project)
    stem = os.path.splitext(base)[0]
    os.makedirs(dest)
    copied = []
    shutil.copy2(project, os.path.join(dest, base))
    copied.append(base)
    for fn in sorted(os.listdir(src_dir)):
        low = fn.lower()
        if fn == base or not low.startswith(stem.lower()):
            continue
        rest = low[len(stem):]
        if rest in COMPANION_EXTS:
            shutil.copy2(os.path.join(src_dir, fn), os.path.join(dest, fn))
            copied.append(fn)
    gdb_src = os.path.join(src_dir, stem + ".gdb")
    if os.path.isdir(gdb_src):
        shutil.copytree(gdb_src, os.path.join(dest, stem + ".gdb"))
        copied.append(stem + ".gdb/ (tree)")
    return os.path.join(dest, base), copied


def arcpy_inventory(path, issues, notes):
    """经 arcpy.mp 打开（path 已是待盘点路径），枚举地图/图层/表/布局。"""
    from arcpy import mp
    tmpdir = tempfile.mkdtemp(prefix="verify-project-")
    work_copy = os.path.join(tmpdir, os.path.basename(path))
    shutil.copy2(path, work_copy)
    stem = os.path.splitext(os.path.basename(path))[0]
    gdb_src = os.path.join(os.path.dirname(os.path.abspath(path)), stem + ".gdb")
    sibling_gdb_copied = False
    if os.path.isdir(gdb_src):
        try:
            shutil.copytree(gdb_src, os.path.join(tmpdir, stem + ".gdb"))
            sibling_gdb_copied = True
        except Exception as exc:
            notes.append("sibling .gdb copy failed: %s" % exc)
    try:
        try:
            aprx = mp.ArcGISProject(work_copy)
        except Exception as exc:
            return None, "OPEN_PROJECT_FAILED: %s" % exc
        out = {"mode": "headless-saved-state",
               "sibling_gdb_copied": sibling_gdb_copied}
        fp, _ = _try_attrs(aprx, ["filePath"])
        out["project_file"] = _safe_str(fp)
        dgdb, _ = _try_attrs(aprx, ["defaultGeodatabase"])
        out["default_geodatabase"] = _safe_str(dgdb)

        maps_out = []
        for m in _to_list(_try_attrs(aprx, ["listMaps"])[0]):
            if m is None:
                continue
            mname, _ = _try_attrs(m, ["name"])
            mtype, _ = _try_attrs(m, ["mapType"])
            m_entry = {"name": _safe_str(mname), "map_type": _safe_str(mtype),
                       "layers": [], "tables": []}
            for ly in _to_list(_try_attrs(m, ["listLayers"])[0]):
                if ly is None:
                    continue
                nm, _ = _try_attrs(ly, ["name"])
                vis, _ = _try_attrs(ly, ["visible"])
                broken, _ = _try_attrs(ly, ["isBroken"])
                ds, _ = _try_attrs(ly, ["dataSource"])
                m_entry["layers"].append({
                    "name": _safe_str(nm),
                    "visible": vis if isinstance(vis, bool) else None,
                    "is_broken": broken if isinstance(broken, bool) else None,
                    "data_source": _safe_str(ds)})
                if broken is True:
                    issues.append("地图 %s 的图层 %s 数据源断裂（is_broken）"
                                  % (_safe_str(mname), _safe_str(nm)))
            for t in _to_list(_try_attrs(m, ["listTables"])[0]):
                if t is None:
                    continue
                nm, _ = _try_attrs(t, ["name"])
                ds, _ = _try_attrs(t, ["dataSource"])
                broken, _ = _try_attrs(t, ["isBroken"])
                m_entry["tables"].append({
                    "name": _safe_str(nm), "data_source": _safe_str(ds),
                    "is_broken": broken if isinstance(broken, bool) else None})
            maps_out.append(m_entry)
        out["maps"] = maps_out
        layouts_out = []
        for lo in _to_list(_try_attrs(aprx, ["listLayouts"])[0]):
            if lo is None:
                continue
            nm, _ = _try_attrs(lo, ["name"])
            pw, _ = _try_attrs(lo, ["pageWidth"])
            ph, _ = _try_attrs(lo, ["pageHeight"])
            frames = None
            try:
                frames = lo.listElements("MAPFRAME_ELEMENT")
            except Exception:
                frames = None
            layouts_out.append({
                "name": _safe_str(nm),
                "page_width": pw if isinstance(pw, (int, float)) else None,
                "page_height": ph if isinstance(ph, (int, float)) else None,
                "map_frame_count": len(_to_list(frames)) if frames is not None else None})
        out["layouts"] = layouts_out
        if not maps_out:
            issues.append("工程没有地图")
        return out, None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="ArcGIS Pro 工程只读盘点 / 迁移验收")
    ap.add_argument("project_pos", nargs="?", default=None, help="工程 .aprx 路径（位置参数）")
    ap.add_argument("--project", default=None, help="工程 .aprx 路径")
    ap.add_argument("--copy-to", default=None, help="先复制工程+伴生文件到该目录，再盘点副本")
    ap.add_argument("--json-out", default=None, help="把 JSON 同时写入该文件")
    args = ap.parse_args()

    project = args.project or args.project_pos
    if not project:
        out = {"ok": False, "error": "MISSING_ARGUMENT",
               "hint": "用法：verify_project.py --project <工程.aprx> [--copy-to <新目录>]",
               "issues": ["未提供工程路径"]}
        return _emit(out, 1, args.json_out)
    if not os.path.isfile(project):
        out = {"ok": False, "error": "FILE_NOT_FOUND", "project": project,
               "issues": ["工程文件不存在：%s" % project]}
        return _emit(out, 1, args.json_out)

    issues = []
    notes = []
    target = project
    copied_files = None
    if args.copy_to:
        if os.path.exists(args.copy_to):
            out = {"ok": False, "error": "COPY_TARGET_EXISTS", "copy_to": args.copy_to,
                   "issues": ["--copy-to 目标已存在，拒绝覆盖：%s" % args.copy_to]}
            return _emit(out, 1, args.json_out)
        target, copied_files = copy_project_tree(project, args.copy_to)

    out = {"ok": True, "project": os.path.abspath(project),
           "copied_to": os.path.abspath(args.copy_to) if args.copy_to else None,
           "copied_files": copied_files,
           "issues": issues, "notes": notes}
    out["file_inventory"] = pure_python_inventory(target, issues)

    try:
        import arcpy  # noqa: F401
    except Exception as exc:
        out["ok"] = False
        out["error"] = "ARCPY_NOT_AVAILABLE"
        out["hint"] = "请用 ArcGIS Pro 自带 Python 运行本脚本；不要把 arcpy 装进无关环境（%s）" % exc
        return _emit(out, 1, args.json_out)

    inv, err = arcpy_inventory(target, issues, notes)
    if err:
        out["ok"] = False
        out["error"] = err
        return _emit(out, 1, args.json_out)
    out["arcpy_inventory"] = inv
    return _emit(out, 0, args.json_out)


if __name__ == "__main__":
    sys.exit(main())
