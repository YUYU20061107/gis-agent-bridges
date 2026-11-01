# -*- coding: utf-8 -*-
"""geocheck.py —— 矢量成果的结构验收（纯 Python，不需要 arcpy，只读）。

存在的理由：lab5 交付被外部核查出三处几何错误（道路分组、空间校正、面裁剪），
而当时"验收"只数了要素个数、看了面积变化，全都通过。几何成果的正确性必须看
结构：

  要素数 ≠ 道路数   → 要查 partCount 与悬空端
  面积变了 ≠ 裁剪对 → 要查环结构（内环）与面积三项闭环
  端点已吸附 ≠ 无缝 → 要按毫米量残余间隙

全部判据来自 docs/REVIEW-lab5-20261101.md，本脚本把它们变成能跑的断言。

用法：
  python geocheck.py parts  <shp>                 # 多部件与悬空端（线）
  python geocheck.py rings  <shp>                 # 环结构 + 内外环面积（面）
  python geocheck.py gaps   <shp> [--tol 0.001]   # 端点残余间隙（线/面）
  python geocheck.py scan   <dir_or_file>...      # 占位符 / 缺 .cpg
  python geocheck.py all    <shp> [--tol 0.001]   # 按几何类型自动跑上面几项
  ... 统一追加 --json-out <file> 保存原始结果

退出码：0 = 无 ERROR 级问题；1 = 有 ERROR；2 = 用法/读取失败。
WARN 不算失败（例如多部件线但每一端都相接），要人来判断。
"""
from __future__ import print_function

import argparse
import json
import os
import struct
import sys
import zipfile

# ---------------------------------------------------------------- shapefile io
_POLYLINE = 3
_POLYGON = 5


def _read_shp(path):
    """返回 (shape_type, [record_dict])，record_dict = {num, parts:[[(x,y)...]]}."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 100:
        raise ValueError("文件短于 shapefile 头: %s" % path)
    code = struct.unpack(">i", data[0:4])[0]
    if code != 9994:
        raise ValueError("不是 shapefile（file code=%d）: %s" % (code, path))
    stype = struct.unpack("<i", data[32:36])[0]
    recs = []
    off = 100
    n = len(data)
    while off + 8 <= n:
        rec_num, content_len = struct.unpack(">ii", data[off:off + 8])
        content = data[off + 8: off + 8 + content_len * 2]
        off += 8 + content_len * 2
        if len(content) < 4:
            continue
        rtype = struct.unpack("<i", content[0:4])[0]
        parts = []
        if rtype in (_POLYLINE, _POLYGON) and len(content) >= 44:
            (num_parts, num_points) = struct.unpack("<ii", content[36:44])
            p_start = 44
            idx = list(struct.unpack("<%di" % num_parts,
                                     content[p_start:p_start + 4 * num_parts]))
            pt_start = p_start + 4 * num_parts
            pts = []
            for k in range(num_points):
                x, y = struct.unpack("<dd", content[pt_start + 16 * k: pt_start + 16 * k + 16])
                pts.append((x, y))
            idx.append(len(pts))
            for k in range(num_parts):
                parts.append(pts[idx[k]:idx[k + 1]])
        elif rtype == 1:  # point
            x, y = struct.unpack("<dd", content[4:20])
            parts.append([(x, y)])
        recs.append({"num": rec_num, "type": rtype, "parts": parts})
    return stype, recs


def _read_dbf(path):
    """返回 (fields, rows)；fields = [(name, type, length, dec)]。"""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 32:
        return [], []
    num_rec = struct.unpack("<I", data[4:8])[0]
    header_len = struct.unpack("<H", data[8:10])[0]
    rec_len = struct.unpack("<H", data[10:12])[0]
    fields = []
    p = 32
    while p < header_len - 1 and data[p] != 0x0D:
        name = data[p:p + 11].split(b"\x00")[0].decode("latin-1")
        ftype = chr(data[p + 11])
        flen = data[p + 16]
        fdec = data[p + 17]
        fields.append((name, ftype, flen, fdec))
        p += 32
    rows = []
    base = header_len
    for i in range(num_rec):
        raw = data[base + i * rec_len: base + (i + 1) * rec_len]
        if len(raw) < rec_len:
            break
        vals = []
        q = 1
        for (name, ftype, flen, fdec) in fields:
            cell = raw[q:q + flen]
            q += flen
            try:
                txt = cell.decode("latin-1")
            except Exception:
                txt = ""
            if ftype in ("C", "M"):
                try:
                    txt = txt.strip().encode("latin-1").decode("gbk")
                except Exception:
                    txt = txt.strip()
            vals.append(txt.strip())
        rows.append(vals)
    return fields, rows


# ------------------------------------------------------------------ geometry
def _plen(ring):
    import math
    return sum(math.hypot(ring[i + 1][0] - ring[i][0], ring[i + 1][1] - ring[i][1])
               for i in range(len(ring) - 1))


def _ring_area(ring):
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _signed_area(ring):
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _dist(a, b):
    import math
    return math.hypot(a[0] - b[0], a[1] - b[1])


def check_parts(shp, tol=1.0):
    """多部件 / 悬空端。一条完整开曲线：partCount==1 且恰好 2 个悬空端。"""
    stype, recs = _read_shp(shp)
    type_name = {3: "Polyline", 5: "Polygon", 1: "Point"}.get(stype, "type%d" % stype)
    issues = []
    feats = []
    for rec in recs:
        parts = rec["parts"]
        ends = [(i, 0, p[0]) for i, p in enumerate(parts)] + \
               [(i, 1, p[-1]) for i, p in enumerate(parts) if len(p) > 1]
        dangling = []
        for (i, tag, p) in ends:
            partner = False
            for (k, tag2, q) in ends:
                if k == i and tag2 == tag:
                    continue
                if _dist(p, q) <= tol:
                    partner = True
                    break
            if not partner:
                dangling.append({"part": i, "end": "start" if tag == 0 else "end",
                                 "xy": [round(p[0], 4), round(p[1], 4)]})
        feats.append({
            "fid": rec["num"] - 1,
            "parts": len(parts),
            "points": sum(len(p) for p in parts),
            "length": round(sum(_plen(p) for p in parts), 3),
            "dangling_ends": len(dangling),
            "dangling": dangling,
        })
        if len(parts) > 1 and type_name == "Polyline":
            issues.append({"level": "WARN", "fid": rec["num"] - 1,
                           "msg": "多部件线（%d 部分）：确认这些部分是否本该是一整条" % len(parts)})
        if type_name == "Polyline" and len(dangling) not in (0, 2):
            issues.append({"level": "ERROR", "fid": rec["num"] - 1,
                           "msg": "悬空端 %d 个（完整开曲线应为 2）：多出的端点说明混入了支路"
                                  % len(dangling)})
    return {"ok": not any(i["level"] == "ERROR" for i in issues),
            "file": shp, "geometry": type_name, "feature_count": len(recs),
            "features": feats, "issues": issues,
            "criteria": {"dangling_tol_m": tol,
                         "expect": "Polyline: parts==1 且 dangling==2；多余部分/端点 = 不是一条完整线"}}


def check_rings(shp, min_holes=0):
    """面：环结构 + 外/内环面积。Erase 造孔后必须 rings==2 且内环有面积。

    min_holes：成果声明应有的内环数。做"挖孔/裁岛"类成果时必须传 1，
    否则只有外环的实现会静默通过（lab5 湖心岛就是这么漏掉的）。
    """
    stype, recs = _read_shp(shp)
    issues = []
    feats = []
    for rec in recs:
        rings = rec["parts"]
        outers, inners = [], []
        for i, r in enumerate(rings):
            a = _signed_area(r)
            (outers if a < 0 else inners).append((i, abs(a), len(r)))
        if not outers:
            outers, inners = [(i, abs(_signed_area(r)), len(r)) for i, r in enumerate(rings)], []
        net = sum(a for _, a, _ in outers) - sum(a for _, a, _ in inners)
        feats.append({"fid": rec["num"] - 1, "rings": len(rings),
                      "outer_rings": len(outers), "inner_rings": len(inners),
                      "outer_area": round(sum(a for _, a, _ in outers), 2),
                      "inner_area": round(sum(a for _, a, _ in inners), 2),
                      "net_area": round(net, 2),
                      "ring_points": [n for _, _, n in outers + inners]})
        if len(rings) > 1 and len(inners) == 0:
            issues.append({"level": "WARN", "fid": rec["num"] - 1,
                           "msg": "多环但未识别出内环：检查环的方向（GeoJSON 反时针=外环）"})
        if min_holes and len(inners) < min_holes:
            issues.append({"level": "ERROR", "fid": rec["num"] - 1,
                           "msg": "要求 %d 个内环，实际 %d 个：剪刀可能跨出了面边界，"
                                  "把孔做成了岸边缺口" % (min_holes, len(inners))})
    return {"ok": not any(i["level"] == "ERROR" for i in issues),
            "file": shp, "feature_count": len(recs), "features": feats, "issues": issues,
            "criteria": {"min_holes": min_holes,
                         "expect": "Erase 造孔后 rings==2（1 外环 + 1 内环）；只有外环说明剪刀跨界成了岸边缺口"}}


def check_gaps(shp, tol=0.001):
    """残余端点间隙：任意两条不同 part 的端点对，取最小距离。"""
    stype, recs = _read_shp(shp)
    import math
    ends = []
    for rec in recs:
        for i, p in enumerate(rec["parts"]):
            if len(p) < 2:
                continue
            ends.append((rec["num"] - 1, i, 0, p[0]))
            ends.append((rec["num"] - 1, i, 1, p[-1]))
    pairs = []
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            fa, pa, ta, qa = ends[a]
            fb, pb, tb, qb = ends[b]
            if fa == fb and pa == pb:
                continue
            d = math.hypot(qa[0] - qb[0], qa[1] - qb[1])
            if d <= max(tol * 1000.0, 1.0):
                pairs.append({"a": [fa, pa, ta], "b": [fb, pb, tb], "gap_m": round(d, 6)})
    pairs.sort(key=lambda z: z["gap_m"])
    nonzero = [p for p in pairs if p["gap_m"] > tol]
    issues = []
    for p in nonzero[:20]:
        issues.append({"level": "ERROR", "msg": "端点间隙 %.4f m > 容差 %.3f m（%s <-> %s）"
                                                % (p["gap_m"], tol, p["a"], p["b"])})
    return {"ok": not issues, "file": shp, "tolerance_m": tol,
            "candidate_pairs": len(pairs), "unclean": len(nonzero),
            "closest": pairs[:12], "issues": issues,
            "criteria": {"expect": "吸附后不应存在 > 容差 的端点间隙；lab5 曾残留 1.1/4.0/6.0 mm"}}


# ------------------------------------------------------------------ 交付件扫描
_PLACEHOLDERS = ("XXX", "XXXX", "XXXXX", "XXXXXXX", "XXXXXXXX", "学号-姓名", "姓名-学号")


def _texts_in(path):
    """抽出可搜索文本：docx/xlsx/pptx 走 zip+xml，其他按文本读（失败返回空）。"""
    low = path.lower()
    out = []
    if low.endswith((".docx", ".xlsx", ".pptx")):
        try:
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if n.endswith(".xml") or n.endswith(".rels"):
                        try:
                            out.append((n, z.read(n).decode("utf-8", "ignore")))
                        except Exception:
                            pass
        except Exception:
            pass
    else:
        try:
            with open(path, "rb") as f:
                out.append(("<file>", f.read().decode("utf-8", "ignore")))
        except Exception:
            pass
    return out


def scan_paths(paths):
    """占位符 + 缺 .cpg 检查。"""
    issues = []
    checked = 0
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for name in files:
                    if any(ph in name for ph in _PLACEHOLDERS):
                        issues.append({"level": "ERROR", "path": os.path.join(root, name),
                                       "msg": "文件名含占位符"})
                for name in files:
                    if name.lower().endswith(".shp"):
                        cpg = os.path.join(root, os.path.splitext(name)[0] + ".cpg")
                        if not os.path.exists(cpg):
                            issues.append({"level": "WARN", "path": os.path.join(root, name),
                                           "msg": "缺 .cpg 编码文件（下游可能要猜 GBK/UTF-8）"})
                for name in sorted(files):
                    full = os.path.join(root, name)
                    if not name.lower().endswith((".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv")):
                        continue
                    checked += 1
                    for where, txt in _texts_in(full):
                        for ph in _PLACEHOLDERS:
                            if ph in txt:
                                issues.append({"level": "ERROR", "path": full,
                                               "msg": "正文含占位符 %r（%s）" % (ph, where)})
                                break
        else:
            if any(ph in os.path.basename(p) for ph in _PLACEHOLDERS):
                issues.append({"level": "ERROR", "path": p, "msg": "文件名含占位符"})
            if p.lower().endswith((".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv")):
                checked += 1
                for where, txt in _texts_in(p):
                    for ph in _PLACEHOLDERS:
                        if ph in txt:
                            issues.append({"level": "ERROR", "path": p,
                                           "msg": "正文含占位符 %r（%s）" % (ph, where)})
                            break
    return {"ok": not any(i["level"] == "ERROR" for i in issues),
            "files_checked": checked, "issues": issues,
            "criteria": {"placeholders": list(_PLACEHOLDERS),
                         "expect": "交付前 0 命中；文件名、正文、邮件标题都要扫"}}


def _emit(obj, json_out=None):
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    if json_out:
        with open(json_out, "wb") as f:
            f.write(txt.encode("utf-8"))
    print(txt)
    return 0 if obj.get("ok") else 1


def main():
    ap = argparse.ArgumentParser(prog="geocheck")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("parts", "rings", "gaps", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("shp")
        if name in ("parts", "gaps", "all"):
            sp.add_argument("--tol", type=float, default=None)
        if name in ("rings", "all"):
            sp.add_argument("--min-holes", type=int, default=0,
                            help="成果应含的内环数；裁岛/挖孔类成果必须传 1")
        sp.add_argument("--json-out")
    sc = sub.add_parser("scan")
    sc.add_argument("paths", nargs="+")
    sc.add_argument("--json-out")
    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        if args.cmd == "scan":
            return _emit(scan_paths(args.paths), args.json_out)
        stype, _recs = _read_shp(args.shp)
        rtype = {3: "polyline", 5: "polygon", 1: "point"}.get(stype, "other")
        if args.cmd == "parts":
            return _emit(check_parts(args.shp, args.tol if args.tol is not None else 1.0), args.json_out)
        if args.cmd == "gaps":
            return _emit(check_gaps(args.shp, args.tol if args.tol is not None else 0.001), args.json_out)
        if args.cmd == "rings":
            return _emit(check_rings(args.shp, args.min_holes), args.json_out)
        # all
        out = {"ok": True, "file": args.shp, "geometry": rtype,
               "checks": {"parts": check_parts(args.shp, args.tol if args.tol is not None else 1.0),
                          "gaps": check_gaps(args.shp, args.tol if args.tol is not None else 0.001)}}
        if rtype == "polygon":
            out["checks"]["rings"] = check_rings(args.shp, args.min_holes)
        out["ok"] = all(v.get("ok", True) for v in out["checks"].values())
        return _emit(out, args.json_out)
    except Exception as exc:  # 结构化失败，不裸 traceback
        return _emit({"ok": False, "error": "GEOCHECK_FAILED",
                      "message": "%s: %s" % (type(exc).__name__, exc),
                      "file": getattr(args, "shp", None)}, getattr(args, "json_out", None))


if __name__ == "__main__":
    sys.exit(main())
