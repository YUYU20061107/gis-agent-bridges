#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""add_scene_xml.py —— 把 make_scene_xml.py 生成的场景 XML 注入 SuperMap 工作空间。

写操作：必须带 --confirm；默认先备份 .smwu；只应在**工作空间副本**上使用（skill 安全纪律）。
运行环境：带 iobjectspy 的 Python。

用法：
    python add_scene_xml.py --workspace workspace.smwu --name 轨迹三维场景 \
        --xml scene.xml --confirm [--replace]

输出单行 JSON：{added, before, after, scene, layers, xml_len, backup, workspace}
"""
import argparse
import datetime
import io
import json
import os
import re
import shutil
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--xml", required=True)
    ap.add_argument("--confirm", action="store_true", help="写操作必须显式确认")
    ap.add_argument("--replace", action="store_true", help="同名场景存在时先删除再添加")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    if not args.confirm:
        print(json.dumps({"ok": False, "error": "需要 --confirm（写操作）",
                          "hint": "只在工作空间副本上注入，并确认 iDesktop 已关闭"},
                         ensure_ascii=False))
        return 2

    try:
        from iobjectspy import Workspace
        from iobjectspy.data import WorkspaceConnectionInfo
    except ImportError:
        print(json.dumps({"ok": False, "error": "IOBJECTSPY_NOT_AVAILABLE",
                          "hint": "请用带 iobjectspy 的 Python 运行"}, ensure_ascii=False))
        return 1

    scene_xml = io.open(args.xml, encoding="utf-8").read()
    if "<sml:Scene>" not in scene_xml:
        print(json.dumps({"ok": False, "error": "不是场景 XML"}, ensure_ascii=False))
        return 2
    if "DataSourceAlias" not in scene_xml:
        print(json.dumps({"ok": False, "error": "场景里没有图层"},
                         ensure_ascii=False))
        return 2

    backup = None
    if not args.no_backup:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        root, ext = os.path.splitext(args.workspace)
        backup = "%s.bak-%s%s" % (root, stamp, ext)
        shutil.copy2(args.workspace, backup)

    ws = Workspace()
    ws = ws.open(WorkspaceConnectionInfo(args.workspace))
    scenes = ws._jobject.getScenes()
    before = scenes.getCount()
    replaced = False
    try:
        if scenes.getSceneXML(args.name) is not None:
            if not args.replace:
                ws.close()
                print(json.dumps({"ok": False, "error": "同名场景已存在", "name": args.name,
                                  "hint": "加 --replace 或换个 --name"}, ensure_ascii=False))
                return 3
            scenes.remove(args.name)
            replaced = True
    except Exception:
        pass
    idx = scenes.add(args.name, scene_xml)
    after = scenes.getCount()
    back = scenes.getSceneXML(args.name) or ""
    layers = re.findall(r"<sml:LayerName>(.*?)</sml:LayerName>", back)
    ws.save()
    ws.close()
    print(json.dumps({
        "ok": True, "workspace": os.path.abspath(args.workspace),
        "backup": backup, "added": args.name, "index": idx,
        "before": before, "after": after, "replaced": replaced,
        "xml_len": len(back), "layers": layers,
        "note": "写后请用 verify_workspace.py --copy-to <新目录> 重开核验；"
                "渲染与截图需在 iDesktop 中打开场景确认",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
