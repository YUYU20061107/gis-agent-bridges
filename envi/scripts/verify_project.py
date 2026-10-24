#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_project.py —— ENVI 栅格工程盘点/迁移验收（只读，纯 Python）。

复用 envi_bridge.py 的 .hdr 解析（纯标准库，不需要 ENVI、不碰许可）：
盘点每个 .hdr 的波段/尺寸/数据类型/interleave、期望字节数与数据文件
实际大小核对，并检查伴生文件完整性（.hdr+数据文件对、.shp 系侧文件）。
--copy-to 会先把工程文件与伴生文件复制到新目录，再对副本重新盘点，
用于验收“换目录后文件对是否还完整”。

用法：
  python verify_project.py <目录 | .hdr | 栅格数据文件>
  python verify_project.py <目录 | .hdr> --copy-to <新目录>

输出结构化 JSON（含 issues 列表）到 stdout；目标不存在或全部 .hdr
解析失败时输出 {"ok": false, "error": ...} 并以退出码 1 结束，
绝不输出裸 traceback。
"""
import argparse
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envi_bridge  # noqa: E402  复用 parse/hdr_summary/find_data_file/find_hdr_file

SHP_SIDECARS = (".shp", ".shx", ".dbf")
DATA_EXTS = envi_bridge.DATA_EXTS


def _companions(path):
    """与 path 同主名的全部伴生文件（.hdr+数据对、.shp 系等）。"""
    folder = os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    out = []
    try:
        names = sorted(os.listdir(folder))
    except Exception:
        return out
    for name in names:
        full = os.path.join(folder, name)
        if os.path.isfile(full) and os.path.splitext(name)[0] == stem:
            out.append(full)
    return out


def copy_project_tree(target, dest):
    """把工程（文件对或整目录）复制到 dest，返回副本侧的盘点目标路径。"""
    if os.path.isdir(target):
        shutil.copytree(target, dest)
        return dest
    os.makedirs(dest)
    for src in _companions(target):
        shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
    if not os.path.isfile(os.path.join(dest, os.path.basename(target))):
        shutil.copy2(target, os.path.join(dest, os.path.basename(target)))
    return os.path.join(dest, os.path.basename(target))


def collect_hdr_files(target):
    hdr_files = []
    if os.path.isdir(target):
        for root, _dirs, files in os.walk(target):
            for name in sorted(files):
                if name.lower().endswith(".hdr"):
                    hdr_files.append(os.path.join(root, name))
    elif target.lower().endswith(".hdr"):
        hdr_files = [target]
    else:
        hdr = envi_bridge.find_hdr_file(target)
        if hdr:
            hdr_files = [hdr]
    return sorted(hdr_files)


def check_companions(target, issues):
    """伴生文件完整性：孤儿数据文件、.shp 系缺侧文件，只记 issue 不修复。"""
    folders = set()
    if os.path.isdir(target):
        for root, _dirs, _files in os.walk(target):
            folders.add(root)
    else:
        folders.add(os.path.dirname(os.path.abspath(target)))
    for folder in sorted(folders):
        try:
            names = sorted(os.listdir(folder))
        except Exception:
            continue
        stems = {}
        for name in names:
            full = os.path.join(folder, name)
            if not os.path.isfile(full):
                continue
            stem, ext = os.path.splitext(name)
            stems.setdefault(stem, set()).add(ext.lower())
        for stem, exts in sorted(stems.items()):
            if ".shp" in exts:
                missing = [e for e in SHP_SIDECARS if e not in exts]
                if missing:
                    issues.append("shapefile %s 缺侧文件: %s"
                                  % (os.path.join(folder, stem + ".shp"),
                                     ", ".join(missing)))
            data_exts = [e for e in exts if e in DATA_EXTS and e != ".hdr"]
            if data_exts and ".hdr" not in exts:
                issues.append("数据文件缺配套 .hdr: %s（扩展名 %s）"
                              % (os.path.join(folder, stem), ", ".join(data_exts)))


def inventory(target):
    out = {"ok": True, "target": os.path.abspath(target), "issues": []}
    hdr_files = collect_hdr_files(target)
    if not hdr_files:
        out["ok"] = False
        out["error"] = "NO_HDR_FOUND"
        out["issues"].append("未找到任何 .hdr 文件: %s" % target)
        out["rasters"] = []
        return out
    rasters = []
    for hdr in hdr_files:
        try:
            entry = envi_bridge.hdr_summary(hdr)
            entry["ok"] = True
        except Exception as e:
            entry = {"hdr": hdr, "ok": False,
                     "error_code": "HDR_PARSE_FAILED", "message": str(e)}
            out["issues"].append(".hdr 解析失败 %s: %s" % (hdr, e))
        if entry.get("ok"):
            if entry.get("data_file") is None:
                out["issues"].append("数据文件缺失（只有 .hdr）: %s" % hdr)
            if entry.get("size_matches") is False:
                out["issues"].append(
                    "数据大小不符 %s: 期望 %s(+offset) 实际 %s"
                    % (hdr, entry.get("expected_data_bytes"),
                       entry.get("data_bytes")))
            if None in (entry.get("samples"), entry.get("lines"),
                        entry.get("bands")):
                out["issues"].append(".hdr 核心字段缺失: %s" % hdr)
        rasters.append(entry)
    check_companions(target, out["issues"])
    out["raster_count"] = len(rasters)
    out["parsed"] = sum(1 for r in rasters if r.get("ok"))
    out["rasters"] = rasters
    if out["parsed"] == 0:
        out["ok"] = False
        out["error"] = "HDR_PARSE_FAILED"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="目录 | .hdr | 栅格数据文件")
    ap.add_argument("--copy-to", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    try:
        if not os.path.exists(args.target):
            print(json.dumps({"ok": False, "error": "FILE_NOT_FOUND",
                              "message": "目标不存在: %s" % args.target},
                             ensure_ascii=False))
            return 1
        target = args.target
        copied_to = None
        if args.copy_to:
            if os.path.exists(args.copy_to):
                print(json.dumps({"ok": False, "error": "COPY_DEST_EXISTS",
                                  "message": "目标已存在，换一个目录: %s"
                                             % args.copy_to},
                                 ensure_ascii=False))
                return 1
            target = copy_project_tree(args.target, args.copy_to)
            copied_to = args.copy_to
        out = inventory(target)
        out["copied_to"] = copied_to
        text = json.dumps(out, ensure_ascii=False, indent=1)
        print(text)
        if args.json_out:
            io.open(args.json_out, "w", encoding="utf-8").write(text)
        return 0 if out.get("ok") else 1
    except Exception as e:  # 绝不裸 traceback：任何异常都转结构化 JSON
        print(json.dumps({"ok": False, "error": "VERIFY_FAILED",
                          "message": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
