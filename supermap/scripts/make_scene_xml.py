#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_scene_xml.py —— 从模板生成 SuperMap 三维球面场景 XML（纯标准库，Python 3.x）。

模板默认取本包 templates/scene_globe_template.xml（iDesktop 10i 示例 CBD.smwu 的场景 XML）。
只做 XML 替换，不连接 SuperMap；生成后用 add_scene_xml.py 注入工作空间。

用法（JSON 规格，推荐）：
    python make_scene_xml.py --spec scene_spec.json --out scene.xml

scene_spec.json 示例：
{
  "name": "轨迹三维场景",
  "camera": {"lon": 160.0, "lat": 50.0, "alt": 15000000},
  "layers": [
    {"datasource": "jidi", "dataset": "zhongdajidi24_zhongdajidi",
     "caption": "2024 轨迹点", "type": "Point",
     "bounds": [113.62, 206.20, 85.03, 22.10]}
  ]
}
bounds 顺序固定为 [left, right, top, bottom]（与 SuperMap Rect2D 一致）。

也可以不用 spec，直接命令行给参数：
    --name 名称 --camera lon,lat,alt \
    --layer alias:dataset:type:caption:left,right,top,bottom （可重复）
"""
import argparse
import io
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TPL = os.path.join(HERE, "..", "templates", "scene_globe_template.xml")


def ecef(lon, lat, h):
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    rl, rp = math.radians(lon), math.radians(lat)
    n = a / math.sqrt(1 - e2 * math.sin(rp) ** 2)
    return ((n + h) * math.cos(rp) * math.cos(rl),
            (n + h) * math.cos(rp) * math.sin(rl),
            (n * (1 - e2) + h) * math.sin(rp))


def sm_frame(v):
    x, y, z = v
    return (y, z, -x)


def norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def quat_from_matrix(m):
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        return (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    if m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        return ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
    return ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)


def camera_block(lon, lat, alt):
    p = sm_frame(ecef(lon, lat, alt))
    up_hint = sm_frame((0.0, 0.0, 1.0))
    f = norm((-p[0], -p[1], -p[2]))
    s = norm(cross(f, up_hint))
    u = cross(s, f)
    r = ((s[0], u[0], -f[0]),
         (s[1], u[1], -f[1]),
         (s[2], u[2], -f[2]))
    q = quat_from_matrix(r)
    return (p, q)


def sub_first(text, tag, value):
    return re.sub(r"(<sml:%s>).*?(</sml:%s>)" % (tag, tag),
                  lambda m: m.group(1) + value + m.group(2), text, count=1)


def make_layer(base, layer):
    b = base
    for tag, value in (("Caption", layer["caption"]),
                       ("DataSourceAlias", "%s@%s" % (layer["dataset"], layer["datasource"])),
                       ("LayerName", "%s@%s" % (layer["dataset"], layer["datasource"])),
                       ("DatasetType", layer["type"])):
        b = sub_first(b, tag, value)
    left, right, top, bottom = [float(x) for x in layer["bounds"]]
    rect = ("<sml:Rect2D>\n"
            "<sml:Left>%.6f</sml:Left>\n<sml:Right>%.6f</sml:Right>\n"
            "<sml:Top>%.6f</sml:Top>\n<sml:Bottom>%.6f</sml:Bottom>\n"
            "</sml:Rect2D>") % (left, right, top, bottom)
    b = re.sub(r"<sml:Rect2D>.*?</sml:Rect2D>", rect, b, count=1, flags=re.S)
    return b


def build(template_path, spec):
    tpl = io.open(template_path, encoding="utf-8").read()
    blocks = re.findall(r"<sml:Layer>.*?</sml:Layer>", tpl, re.S)
    if not blocks:
        raise SystemExit("模板里找不到 <sml:Layer> 块：%s" % template_path)
    base = blocks[0]

    cam_in = spec.get("camera", {})
    lon = float(cam_in.get("lon", 0.0))
    lat = float(cam_in.get("lat", 0.0))
    alt = float(cam_in.get("alt", 15000000.0))
    p, q = camera_block(lon, lat, alt)

    layers = [make_layer(base, item) for item in spec["layers"]]
    scene = tpl
    scene = sub_first(scene, "Name", spec.get("name", "三维场景"))
    scene = re.sub(r"<sml:Layers>.*</sml:Layers>",
                   "<sml:Layers>\n" + "\n".join(layers) + "\n</sml:Layers>",
                   scene, count=1, flags=re.S)
    cam = ("<sml:Cameras>\n<sml:Camera>\n<sml:Name>name</sml:Name>\n"
           "<sml:camPosition>\n<sml:x>%.6f</sml:x>\n<sml:y>%.6f</sml:y>\n<sml:z>%.6f</sml:z>\n</sml:camPosition>\n"
           "<sml:Orientation>\n<sml:x>%.9f</sml:x>\n<sml:y>%.9f</sml:y>\n<sml:z>%.9f</sml:z>\n<sml:w>%.9f</sml:w>\n</sml:Orientation>\n"
           "<sml:ProjectionType3D>PT_PERSPECTIVE</sml:ProjectionType3D>\n"
           "<sml:CollisionDetection>FALSE</sml:CollisionDetection>\n"
           "<sml:CollisionDistance>0.50</sml:CollisionDistance>\n</sml:Camera>\n</sml:Cameras>") % (
        p[0], p[1], p[2], q[0], q[1], q[2], q[3])
    scene = re.sub(r"<sml:Cameras>.*</sml:Cameras>", cam, scene, count=1, flags=re.S)
    return scene, p, q


def parse_layer_arg(text):
    parts = text.split(":", 4)
    if len(parts) != 5:
        raise SystemExit("--layer 需要 alias:dataset:type:caption:l,r,t,b，实际：%s" % text)
    alias, dataset, dstype, caption, b = parts
    left, right, top, bottom = [float(x) for x in b.split(",")]
    return {"datasource": alias, "dataset": dataset, "type": dstype,
            "caption": caption, "bounds": [left, right, top, bottom]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=DEFAULT_TPL)
    ap.add_argument("--spec", help="JSON 规格文件；给了就不再读 --name/--camera/--layer")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="三维场景")
    ap.add_argument("--camera", default="0,0,15000000", help="lon,lat,alt（米）")
    ap.add_argument("--layer", action="append", default=[])
    args = ap.parse_args()

    if args.spec:
        spec = json.load(io.open(args.spec, encoding="utf-8-sig"))
    else:
        lon, lat, alt = [float(x) for x in args.camera.split(",")]
        layers = [parse_layer_arg(x) for x in args.layer]
        if not layers:
            raise SystemExit("至少给一个 --layer，或使用 --spec")
        spec = {"name": args.name, "camera": {"lon": lon, "lat": lat, "alt": alt}, "layers": layers}

    scene, p, q = build(args.template, spec)
    io.open(args.out, "w", encoding="utf-8").write(scene)
    print(json.dumps({
        "out": os.path.abspath(args.out),
        "bytes": len(scene.encode("utf-8")),
        "layers": len(spec["layers"]),
        "scene": spec.get("name"),
        "camera_pos": ["%.3f" % c for c in p],
        "quat": ["%.6f" % c for c in q],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
