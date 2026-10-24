#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_project.py —— QGIS 工程盘点/迁移验收（只读，纯标准库）。

复用同目录 qgis_bridge.py 的纯 Python 解析实现（.qgs XML / .qgz 内的 .qgs），
不装 QGIS 也能盘点：工程标题、画布 CRS、图层（名称/类型/数据源/提供者/CRS）、
图层树、打印布局，并逐个图层核对数据源文件在本机是否存在、shapefile
伴生文件（.shx/.dbf 等）是否齐全，问题汇总进 issues 列表。

--copy-to <dir>：先把工程文件、同主名伴生文件，以及各图层引用的本地
数据源文件（连同其同主名伴生文件）复制到新目录，再对**副本**重新盘点，
用于验收“换目录/换机器后工程还能不能打开、数据源还连不连得上”。
复制只读原件；目标目录已存在时结构化报错，不覆盖。

任何失败都输出结构化 JSON（{"ok": false, "error": ...}）并以退出码 1
结束，绝不裸 traceback。成功盘点退出码 0（issues 非空只代表发现问题，
不代表脚本失败）。

用法：
  python verify_project.py <工程.qgs|.qgz>
  python verify_project.py <工程.qgs|.qgz> --copy-to <新目录>
  python verify_project.py <工程.qgs|.qgz> --json-out report.json
"""
import argparse
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qgis_bridge import _parse_project_xml  # noqa: E402  纯标准库解析实现
# 注意：qgis_bridge 导入时已把 sys.stdout 包装为 UTF-8，这里不要重复包装
# （双重 TextIOWrapper 会在先包装者回收时关掉底层 buffer）。

# 同主名伴生文件扩展名：shapefile 一套件、栅格/矢量常见旁置文件
_COMPANION_EXTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".sbn",
                   ".sbx", ".idx", ".qix", ".tfw", ".aux.xml", ".xml",
                   ".gpkg", ".sqlite", ".tif", ".tiff", ".vrt", ".geojson",
                   ".json", ".csv", ".ovr")
# shapefile 必须成套出现的核心伴生扩展名（缺一即记 issue）
_SHP_REQUIRED = (".shx", ".dbf")


def _emit(obj, code):
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    print(text)
    return code, text


def _datasource_file_part(raw):
    """把 QGIS 数据源字符串尽量还原成本地文件路径；不是本地文件时返回 None。

    形如：./data/roads.shp、roads.shp|layername=roads、
    /abs/path/data.gpkg|layername=x、PG:dbname=... （后者不是文件）。
    """
    if not raw or not isinstance(raw, str):
        return None
    part = raw.split("|", 1)[0].strip().strip('"')
    if not part:
        return None
    low = part.lower()
    if "://" in part or low.startswith(
            ("pg:", "dbname", "host=", "service=", "ogr:", "gdal:",
             "wms:", "wfs:", "xyz:", "memory:", "mssql:", "oracle:")):
        return None  # URL 或数据库/提供者连接字符串，不是本地文件
    if "=" in part and "/" not in part and os.sep not in part:
        return None  # key=value 风格的提供者字符串（如内存图层）
    return part


def _resolve(raw, project_dir):
    """返回 (候选本地路径 or None, 是否文件式数据源)。"""
    part = _datasource_file_part(raw)
    if part is None:
        return None, False
    if os.path.isabs(part):
        return part, True
    # 只有带路径分隔符或像文件名（有扩展名）的才当文件式处理
    if "/" in part or os.sep in part or "." in os.path.basename(part):
        return os.path.normpath(os.path.join(project_dir, part)), True
    return None, False


def _companions_of(path):
    """同主名伴生文件清单（含 path 本身若存在）。"""
    root, _ext = os.path.splitext(path)
    found = []
    parent = os.path.dirname(path) or "."
    base = os.path.basename(root)
    try:
        names = os.listdir(parent)
    except Exception:
        return found
    for name in names:
        low = name.lower()
        if name == os.path.basename(path):
            found.append(os.path.join(parent, name))
        elif low.startswith(base.lower()) and \
                low[len(base):] in _COMPANION_EXTS:
            found.append(os.path.join(parent, name))
    return sorted(found)


def _inventory(path):
    """对 path 盘点；返回 (out_dict, hard_error_dict_or_None)。"""
    notes = []
    if not os.path.isfile(path):
        return None, {"ok": False, "error": "FILE_NOT_FOUND",
                      "project": os.path.abspath(path),
                      "hint": "工程文件不存在，先核对路径原文"}
    if os.path.splitext(path)[1].lower() not in (".qgs", ".qgz"):
        return None, {"ok": False, "error": "UNSUPPORTED_FORMAT",
                      "project": os.path.abspath(path),
                      "hint": "仅支持 .qgs / .qgz 工程文件"}
    try:
        parsed = _parse_project_xml(path, notes)
    except Exception as e:
        return None, {"ok": False, "error": "PARSE_FAILED",
                      "project": os.path.abspath(path),
                      "message": "%s: %s" % (type(e).__name__, e),
                      "notes": notes,
                      "hint": "工程文件可能损坏或版本过新；如实回报，不要反复换环境试探"}
    project_dir = os.path.dirname(os.path.abspath(path))
    issues = []
    layers = []
    for layer in parsed.get("layers", []):
        entry = dict(layer)
        resolved, is_file = _resolve(entry.get("datasource"), project_dir)
        entry["datasource_resolved"] = resolved
        if is_file:
            entry["datasource_exists"] = os.path.isfile(resolved)
            if not entry["datasource_exists"]:
                issues.append("图层 %s 的数据源文件缺失: %s"
                              % (entry.get("name"), resolved))
            elif resolved.lower().endswith(".shp"):
                for ext in _SHP_REQUIRED:
                    sib = os.path.splitext(resolved)[0] + ext
                    if not os.path.isfile(sib):
                        issues.append("图层 %s 的 shapefile 伴生文件缺失: %s"
                                      % (entry.get("name"), sib))
        else:
            entry["datasource_exists"] = None
        layers.append(entry)
    if not layers:
        issues.append("工程没有图层")
    out = {"ok": True,
           "project": os.path.abspath(path),
           "format_inner": parsed.get("format_inner"),
           "qgis_version_attr": parsed.get("qgis_version_attr"),
           "title": parsed.get("title"),
           "canvas_crs_authid": parsed.get("canvas_crs_authid"),
           "layer_count": len(layers),
           "layers": layers,
           "layer_tree": parsed.get("layer_tree"),
           "layouts": parsed.get("layouts"),
           "notes": notes,
           "issues": issues}
    return out, None


def _copy_tree(project, dest):
    """复制工程 + 同主名伴生 + 各图层本地数据源（带伴生）到 dest。

    返回 (副本工程路径, 已复制文件相对清单)。
    """
    os.makedirs(dest)
    src_dir = os.path.dirname(os.path.abspath(project))
    copied = []

    def put(src_path):
        rel = os.path.relpath(src_path, src_dir)
        if rel.startswith(".."):
            return  # 工程目录之外的数据源不复制，只在盘点里如实标注
        target = os.path.join(dest, rel)
        tdir = os.path.dirname(target)
        if tdir and not os.path.isdir(tdir):
            os.makedirs(tdir)
        if os.path.abspath(src_path) != os.path.abspath(target):
            shutil.copy2(src_path, target)
        if rel not in copied:
            copied.append(rel)

    for f in _companions_of(os.path.abspath(project)):
        put(f)
    put(os.path.abspath(project))
    notes = []
    try:
        parsed = _parse_project_xml(os.path.abspath(project), notes)
        for layer in parsed.get("layers", []):
            resolved, is_file = _resolve(layer.get("datasource"), src_dir)
            if is_file and resolved and os.path.isfile(resolved):
                for f in _companions_of(resolved):
                    put(f)
                put(resolved)
    except Exception:
        pass  # 复制阶段解析失败不致命，随后对副本盘点会结构化报错
    return os.path.join(dest, os.path.basename(project)), sorted(copied)


def main():
    ap = argparse.ArgumentParser(prog="verify_project")
    ap.add_argument("project", help=".qgs / .qgz 工程文件路径")
    ap.add_argument("--copy-to", default=None,
                    help="先复制工程与伴生/数据源文件到该新目录，再盘点副本")
    ap.add_argument("--json-out", default=None, help="把 JSON 另存到该路径")
    args = ap.parse_args()

    path = args.project
    copied_to = None
    copied_files = None
    if args.copy_to:
        if os.path.exists(args.copy_to):
            code, _t = _emit({"ok": False, "error": "COPY_TARGET_EXISTS",
                              "project": os.path.abspath(path),
                              "copied_to": args.copy_to,
                              "hint": "目标目录已存在，换一个新目录（不覆盖）"}, 1)
            return code
        if not os.path.isfile(path):
            code, _t = _emit({"ok": False, "error": "FILE_NOT_FOUND",
                              "project": os.path.abspath(path),
                              "hint": "工程文件不存在，先核对路径原文"}, 1)
            return code
        path, copied_files = _copy_tree(path, args.copy_to)
        copied_to = args.copy_to

    out, err = _inventory(path)
    if err is not None:
        if copied_to is not None:
            err["copied_to"] = copied_to
            err["copied_files"] = copied_files
        code, _t = _emit(err, 1)
        return code
    if copied_to is not None:
        out["copied_to"] = copied_to
        out["copied_files"] = copied_files
        out["source_project"] = os.path.abspath(args.project)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if args.json_out:
        with io.open(args.json_out, "w", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
