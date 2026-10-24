#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_project.py —— MapGIS 工程盘点/迁移验收（只读，探针优先口径）。

两层盘点：
  1) 文件层（纯标准库）：工程文件（.MPJ）与同主名伴生文件的存在性、
     字节数与 sha256、同目录扩展名普查——不需要 MapGIS 即可完成。
  2) 厂商层：依赖 MapGIS Python 绑定（以 probe_mapgis.py 探针结论为准）。
     绑定不可用时输出结构化
       {"ok": false, "error": "MAPGIS_NOT_AVAILABLE", ...}
     并以退出码 1 结束，绝不输出裸 traceback、绝不编造盘点结果。
     本包仍是 EXPLORATORY / UNVERIFIED：厂商层命中也只到
     mapgis_bridge.inspect 同口径的“打开入口 + 成员面”，不解读语义。

--copy-to 会先把工程文件 + 同主名伴生文件复制到新目录，再对副本盘点，
用于验收“换目录后工程文件是否还齐全”。

用法：
  python verify_project.py <工程文件.MPJ>
  python verify_project.py <工程文件.MPJ> --copy-to <新目录>
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_mapgis  # noqa: E402


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(path):
    entry = {"path": path, "bytes": os.path.getsize(path)}
    try:
        entry["sha256"] = sha256_of(path)
    except Exception as e:
        entry["sha256"] = None
        entry["sha256_error"] = str(e)
    return entry


def same_stem_companions(src):
    """同目录下与工程文件同主名的数据文件/目录（与 mapgis_bridge.backup 同口径）。"""
    folder = os.path.dirname(os.path.abspath(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    out = []
    try:
        entries = sorted(os.listdir(folder))
    except Exception:
        return out
    for name in entries:
        if name == os.path.basename(src):
            continue
        if os.path.splitext(name)[0] == stem:
            out.append(os.path.join(folder, name))
    return out


def copy_project_tree(project, dest):
    os.makedirs(dest)
    shutil.copy2(project, os.path.join(dest, os.path.basename(project)))
    for comp in same_stem_companions(project):
        target = os.path.join(dest, os.path.basename(comp))
        if os.path.isdir(comp):
            shutil.copytree(comp, target)
        else:
            shutil.copy2(comp, target)
    return os.path.join(dest, os.path.basename(project))


def file_level_inventory(project):
    folder = os.path.dirname(os.path.abspath(project))
    census = {}
    try:
        for name in sorted(os.listdir(folder)):
            full = os.path.join(folder, name)
            if os.path.isfile(full):
                ext = os.path.splitext(name)[1].lower() or "<none>"
                census[ext] = census.get(ext, 0) + 1
    except Exception:
        pass
    companions = []
    for comp in same_stem_companions(project):
        if os.path.isfile(comp):
            companions.append(file_entry(comp))
        else:
            companions.append({"path": comp, "bytes": None,
                               "note": "directory"})
    return {"project": file_entry(project), "companions": companions,
            "directory_extension_census": census}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="MapGIS 工程文件（.MPJ）路径")
    ap.add_argument("--copy-to", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    try:
        if not os.path.isfile(args.project):
            print(json.dumps({"ok": False, "error": "FILE_NOT_FOUND",
                              "message": "工程文件不存在: %s" % args.project},
                             ensure_ascii=False))
            return 1
        project = args.project
        copied_to = None
        if args.copy_to:
            if os.path.exists(args.copy_to):
                print(json.dumps({"ok": False, "error": "COPY_DEST_EXISTS",
                                  "message": "目标已存在，换一个目录: %s"
                                             % args.copy_to},
                                 ensure_ascii=False))
                return 1
            project = copy_project_tree(args.project, args.copy_to)
            copied_to = args.copy_to

        out = {"ok": False, "project": os.path.abspath(project),
               "copied_to": copied_to, "issues": [],
               "files": file_level_inventory(project)}

        probe = probe_mapgis.run_probe()
        out["probe_ok"] = bool(probe.get("ok"))
        if not probe.get("ok"):
            # 厂商层不可用：结构化报错 + 文件层盘点仍然给出，退出码 1
            out["error"] = "MAPGIS_NOT_AVAILABLE"
            out["error_code"] = "MAPGIS_NOT_AVAILABLE"
            out["message"] = ("MapGIS Python 绑定不可用（探针: %s），"
                              "厂商层盘点无法执行；files 为纯文件层盘点，"
                              "不构成工程内容盘点结论。"
                              % probe.get("error_code"))
            out["issues"].append("厂商层不可用: MAPGIS_NOT_AVAILABLE")
            text = json.dumps(out, ensure_ascii=False, indent=1)
            print(text)
            if args.json_out:
                io.open(args.json_out, "w", encoding="utf-8").write(text)
            return 1

        # 厂商层：与 mapgis_bridge.inspect 同口径的有限试探
        import mapgis_bridge
        mod = probe_mapgis.load_found_module()
        if mod is None:
            out["error"] = "MAPGIS_NOT_AVAILABLE"
            out["error_code"] = "MAPGIS_NOT_AVAILABLE"
            out["message"] = "探针结论与重新导入不一致，按不可用处理"
            out["issues"].append("厂商层不可用: MAPGIS_NOT_AVAILABLE")
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        attempts = []
        obj, strategy = mapgis_bridge._try_open_project(mod, project, attempts)
        out["attempts"] = attempts
        if obj is None:
            out["error"] = "NOT_SUPPORTED"
            out["error_code"] = "NOT_SUPPORTED"
            out["message"] = ("已导入模块 %s，但全部候选打开策略均失败；"
                              "不编造盘点结果。" % mod.__name__)
            out["issues"].append("工程打开策略全部失败: NOT_SUPPORTED")
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        out["ok"] = True
        out["opened_via"] = strategy
        out["object_type"] = str(type(obj))
        out["object_public_members"] = [
            n for n in dir(obj) if not n.startswith("_")][:200]
        out["notes"] = ["EXPLORATORY / UNVERIFIED：只到打开入口与成员面，"
                        "不解读语义、不声称已完成数据盘点。"]
        text = json.dumps(out, ensure_ascii=False, indent=1)
        print(text)
        if args.json_out:
            io.open(args.json_out, "w", encoding="utf-8").write(text)
        return 0
    except Exception as e:  # 绝不裸 traceback
        print(json.dumps({"ok": False, "error": "VERIFY_FAILED",
                          "message": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
