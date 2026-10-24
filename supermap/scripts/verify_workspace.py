#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_workspace.py —— SuperMap 工作空间盘点/迁移验收（只读）。

输出 JSON：数据源、数据集（记录数/坐标系统/用户字段）、地图（层数/bounds）、
场景（数量/名称/图层引用），以及可选的字段空值检查。
--copy-to 会先整目录复制（工作空间 + 同级与一级子目录的数据源），再打开副本，
用于验收“换目录后还能不能打开”。

运行环境：带 iobjectspy 的 Python。

用法：
  python verify_workspace.py --workspace workspace.smwu
  python verify_workspace.py --workspace workspace.smwu --copy-to <新目录> --check-field DateStr
"""
import argparse
import io
import json
import os
import re
import shutil
import sys

# stdout 锁定 UTF-8：中文 Windows 管道默认 GBK 编码会让含中文/生僻字的
# JSON 输出乱码或 UnicodeEncodeError 崩溃（与各包无头桥同口径）。
if getattr(sys.stdout, "encoding", None) != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
    except Exception:
        pass



def copy_workspace_tree(workspace, dest):
    src_dir = os.path.dirname(os.path.abspath(workspace))
    base = os.path.basename(workspace)
    os.makedirs(dest)
    shutil.copy2(workspace, os.path.join(dest, base))
    for root, dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        if rel != "." and rel.count(os.sep) > 1:
            continue
        for fn in files:
            if not fn.lower().endswith((".udb", ".udbx", ".udd")):
                continue
            target_dir = os.path.join(dest, rel) if rel != "." else dest
            if not os.path.isdir(target_dir):
                os.makedirs(target_dir)
            shutil.copy2(os.path.join(root, fn), os.path.join(target_dir, fn))
    return os.path.join(dest, base)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--copy-to", default=None)
    ap.add_argument("--check-field", action="append", default=[])
    ap.add_argument("--expect-scene", action="store_true", help="要求至少 1 个场景（缺失记为 issue）")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    try:
        from iobjectspy import Workspace
        from iobjectspy.data import WorkspaceConnectionInfo
    except ImportError:
        print(json.dumps({"ok": False, "error": "IOBJECTSPY_NOT_AVAILABLE",
                          "hint": "请用带 iobjectspy 的 Python 运行"}, ensure_ascii=False))
        return 1

    path = args.workspace
    if args.copy_to:
        if os.path.exists(args.copy_to):
            raise SystemExit("目标已存在：%s（换一个目录）" % args.copy_to)
        path = copy_workspace_tree(path, args.copy_to)

    out = {"workspace": os.path.abspath(path), "copied_to": args.copy_to, "issues": []}
    ws = Workspace()
    ws = ws.open(WorkspaceConnectionInfo(path))

    ds_list = []
    datasources = list(ws.datasources)
    out["datasource_count"] = len(datasources)
    for ds in datasources:
        entry = {"alias": ds.alias, "datasets": []}
        try:
            entry["engine"] = str(ds.connection_info.type)
        except Exception as exc:
            entry["engine"] = "unknown: %s" % exc
        for d in list(ds.datasets):
            info = {"name": d.name}
            try:
                info["records"] = d.get_record_count()
            except Exception:
                info["records"] = None
            try:
                crs = d.prj_coordsys
                crs_name = crs.name
                crs_epsg = None
                try:
                    crs_epsg = crs.to_epsg_code()
                except Exception:
                    crs_epsg = None
                info["crs"] = {"name": crs_name, "epsg": crs_epsg}
                if crs_epsg != 4326 and "WGS" not in (crs_name or ""):
                    out["issues"].append("数据集 %s 坐标系不是 WGS84：%s (%s)" % (d.name, crs_name, crs_epsg))
            except Exception:
                info["crs"] = None
            try:
                info["type"] = str(d.type)
            except Exception:
                info["type"] = None
            try:
                user_fields = []
                for f in d.field_infos:
                    if f.is_system_field():
                        continue
                    user_fields.append({"name": f.name, "type": str(f.type), "length": f.max_length})
                info["user_fields"] = user_fields
            except Exception as exc:
                info["user_fields"] = "n/a: %s" % exc
            for field in args.check_field:
                if field not in [f["name"] for f in info.get("user_fields", []) if isinstance(f, dict)]:
                    info.setdefault("field_empty", {})[field] = "missing"
                    continue
                try:
                    rs = d.get_recordset()
                    empty = 0
                    for i in range(info["records"]):
                        rs.seek_id(i)
                        v = rs.get_value(field)
                        if v is None or v == "":
                            empty += 1
                    rs.close()
                    info.setdefault("field_empty", {})[field] = empty
                    if empty:
                        out["issues"].append("字段 %s 在 %s 有 %d 个空值" % (field, d.name, empty))
                except Exception as exc:
                    info.setdefault("field_empty", {})[field] = "n/a: %s" % exc
            entry["datasets"].append(info)
        ds_list.append(entry)
    out["datasources"] = ds_list

    maps = []
    for m in list(ws.get_maps()):
        item = {"name": m.get_name(), "layers": m.get_layers_count()}
        try:
            b = m.get_bounds()
            item["bounds"] = [b.left, b.bottom, b.right, b.top]
        except Exception:
            item["bounds"] = None
        maps.append(item)
    out["maps"] = maps

    scenes = {"count": 0, "items": []}
    try:
        jobj_scenes = ws._jobject.getScenes()
        scenes["count"] = jobj_scenes.getCount()
        for i in range(scenes["count"]):
            xml = jobj_scenes.getSceneXML(i) or ""
            name = re.search(r"<sml:Name>(.*?)</sml:Name>", xml)
            scenes["items"].append({
                "index": i,
                "name": name.group(1) if name else "?",
                "xml_len": len(xml),
                "layers": re.findall(r"<sml:LayerName>(.*?)</sml:LayerName>", xml),
            })
    except Exception as exc:
        scenes["error"] = str(exc)
        out["issues"].append("场景读取失败：%s" % exc)
    out["scenes"] = scenes

    ws.close()
    if not out["datasources"]:
        out["issues"].append("工作空间没有数据源")
    if not out["maps"]:
        out["issues"].append("工作空间没有地图")
    if scenes["count"] == 0 and args.expect_scene:
        out["issues"].append("场景数为 0（--expect-scene 要求至少 1 个）")

    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if args.json_out:
        io.open(args.json_out, "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
