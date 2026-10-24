# -*- coding: utf-8 -*-
"""verify_project.py —— ArcMap 地图文档（.mxd）盘点/迁移验收（只读）。

盘点必须依赖 arcpy.mapping 枚举数据框/图层/表视图（.mxd 是二进制格式，
没有纯 Python 解析路径）。无 arcpy 时输出结构化 JSON
{"ok": false, "error": "ARCPY_NOT_AVAILABLE", ...} 并以退出码 1 结束，
绝不裸 traceback；其余失败同样结构化输出。

--copy-to <dir>：先把 .mxd、同名 .gdb 文件夹与同主名伴生文件复制到
新目录，再对**副本**重新盘点，用于验收“换目录后还能不能打开、
数据源还连不连得上”。复制只读原件；目标目录已存在时结构化报错。

盘点内容：文档路径/活动视图/页面大小、数据框（名称/范围/比例尺/
空间参考）、图层（名称/数据源/显隐/是否断裂）、独立表视图；
断裂图层、数据源文件缺失、无数据框等问题汇总进 issues 列表。
成功盘点退出码 0（issues 非空只代表发现问题）。

运行环境：ArcMap Desktop 自带的 Python 2.7（或任何可导入 arcpy 的
解释器）；本脚本写在 Python 2.7 / 3.x 兼容子集上。

用法：
  python verify_project.py <文档.mxd>
  python verify_project.py <文档.mxd> --copy-to <新目录>
  python verify_project.py <文档.mxd> --json-out report.json
"""
from __future__ import print_function

import argparse
import json
import os
import shutil
import sys

# 同主名伴生文件扩展名（.mxd 旁置的同名文件，迁移时容易漏带）
_COMPANION_EXTS = (".xml", ".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn",
                   ".sbx", ".lyr")


def _safe_str(v):
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def emit(obj, exit_code=0):
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except Exception:
        try:
            sys.stdout.write(json.dumps(obj, ensure_ascii=True, indent=1) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    return exit_code


def _fail(error, message, **extra):
    obj = {"ok": False, "error": error, "message": message}
    obj.update(extra)
    return emit(obj, exit_code=1)


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
                      ("isBroken", "is_broken"),
                      ("isGroupLayer", "is_group_layer")):
        try:
            entry[key] = getattr(ly, attr)
        except Exception:
            entry[key] = None
    if entry.get("data_source") is not None:
        entry["data_source"] = _safe_str(entry["data_source"])
    return entry


def _copy_tree(document, dest):
    """复制 .mxd + 同名 .gdb 文件夹 + 同主名伴生文件到 dest（新目录）。

    返回 (副本 .mxd 路径, 已复制条目相对清单)。
    """
    os.makedirs(dest)
    src_dir = os.path.dirname(os.path.abspath(document))
    stem = os.path.splitext(os.path.basename(document))[0]
    copied = []
    shutil.copy2(document, os.path.join(dest, os.path.basename(document)))
    copied.append(os.path.basename(document))
    gdb_src = os.path.join(src_dir, stem + ".gdb")
    if os.path.isdir(gdb_src):
        shutil.copytree(gdb_src, os.path.join(dest, stem + ".gdb"))
        copied.append(stem + ".gdb/")
    try:
        names = os.listdir(src_dir)
    except Exception:
        names = []
    for name in names:
        low = name.lower()
        if name == os.path.basename(document):
            continue
        if low.startswith(stem.lower()) and \
                os.path.splitext(low)[1] in _COMPANION_EXTS and \
                os.path.isfile(os.path.join(src_dir, name)):
            shutil.copy2(os.path.join(src_dir, name),
                         os.path.join(dest, name))
            copied.append(name)
    return os.path.join(dest, os.path.basename(document)), sorted(copied)


def _inventory(arcpy, path):
    notes = []
    issues = []
    mxd = arcpy.mapping.MapDocument(path)
    try:
        doc = {"file_path": _safe_str(getattr(mxd, "filePath", None)),
               "active_view": _safe_str(getattr(mxd, "activeView", None))}
        try:
            ps = mxd.pageSize
            doc["page_size"] = {"width": ps.width, "height": ps.height}
        except Exception:
            doc["page_size"] = None
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
                fentry["spatial_reference"] = \
                    _safe_str(getattr(sr, "name", None)) if sr else None
            except Exception:
                fentry["spatial_reference"] = None
            layers = []
            for ly in arcpy.mapping.ListLayers(mxd, "", df):
                entry = _layer_entry(ly)
                if entry.get("is_broken"):
                    issues.append("图层 %s 已断裂（数据源不可达）"
                                  % entry.get("name"))
                ds = entry.get("data_source")
                if ds and ("/" in ds or "\\" in ds) and \
                        not os.path.exists(ds):
                    issues.append("图层 %s 的数据源路径不存在: %s"
                                  % (entry.get("name"), ds))
                layers.append(entry)
            fentry["layers"] = layers
            total_layers += len(layers)
            frames.append(fentry)
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
        if not frames:
            issues.append("文档没有数据框")
        return {"ok": True, "project": os.path.abspath(path),
                "mode": "headless-saved-state",
                "document": doc, "data_frames": frames,
                "layer_count": total_layers, "table_views": tables,
                "notes": notes, "issues": issues}
    finally:
        try:
            del mxd
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(prog="verify_project")
    ap.add_argument("project", help=".mxd 地图文档路径")
    ap.add_argument("--copy-to", default=None,
                    help="先复制文档与伴生文件到该新目录，再盘点副本")
    ap.add_argument("--json-out", default=None, help="把 JSON 另存到该路径")
    args = ap.parse_args()

    try:
        import arcpy  # noqa: F401
    except Exception as e:
        return _fail("ARCPY_NOT_AVAILABLE",
                     "arcpy 导入失败: %s；.mxd 盘点必须用 ArcMap Desktop "
                     "自带 Python（或可导入 arcpy 的解释器）运行" % e,
                     project=os.path.abspath(args.project))

    if not os.path.isfile(args.project):
        return _fail("FILE_NOT_FOUND", "地图文档不存在: %s" % args.project,
                     project=os.path.abspath(args.project))
    if os.path.splitext(args.project)[1].lower() != ".mxd":
        return _fail("UNSUPPORTED_FORMAT",
                     "仅支持 .mxd 地图文档: %s" % args.project,
                     project=os.path.abspath(args.project))

    path = args.project
    copied_to = None
    copied_files = None
    if args.copy_to:
        if os.path.exists(args.copy_to):
            return _fail("COPY_TARGET_EXISTS",
                         "目标目录已存在，换一个新目录（不覆盖）: %s"
                         % args.copy_to,
                         project=os.path.abspath(args.project),
                         copied_to=args.copy_to)
        try:
            path, copied_files = _copy_tree(args.project, args.copy_to)
        except Exception as e:
            return _fail("COPY_FAILED", "复制失败: %s" % e,
                         project=os.path.abspath(args.project),
                         copied_to=args.copy_to)
        copied_to = args.copy_to

    try:
        out = _inventory(arcpy, path)
    except Exception as e:
        return _fail("INSPECT_FAILED", "盘点失败: %s" % e,
                     project=os.path.abspath(path), copied_to=copied_to)
    if copied_to is not None:
        out["copied_to"] = copied_to
        out["copied_files"] = copied_files
        out["source_project"] = os.path.abspath(args.project)
    code = emit(out, exit_code=0)
    if args.json_out:
        try:
            import io
            with io.open(args.json_out, "w", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False, indent=1))
        except Exception as e:
            return _fail("JSON_OUT_FAILED", "写 json-out 失败: %s" % e)
    return code


if __name__ == "__main__":
    sys.exit(main())
