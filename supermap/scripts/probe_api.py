# -*- coding: utf-8 -*-
"""
probe_api.py — iobjectspy API 校准探针（只读）
用途：首次部署或版本变更时运行一次，输出本机 iobjectspy 关键类的真实方法清单，
以及（可选）打开一个工作空间后集合对象的真实形态，供维护者据此收紧桥接脚本。
输出为多行文本（非 JSON），请完整回传，不要删减。
"""
import io
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


def dump_class(mod_name, cls_name):
    print("=" * 60)
    print("CLASS %s.%s" % (mod_name, cls_name))
    try:
        mod = __import__(mod_name, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
    except Exception as e:
        print("  <unavailable: %s>" % e)
        return
    names = [n for n in dir(cls) if not n.startswith("_")]
    for n in names:
        print("  - %s" % n)


def main():
    try:
        import iobjectspy
        print("iobjectspy version:", getattr(iobjectspy, "__version__", "unknown"))
        print("iobjectspy file:", getattr(iobjectspy, "__file__", "unknown"))
        tops = [n for n in dir(iobjectspy) if not n.startswith("_")]
        print("iobjectspy top-level names:", ", ".join(tops))
    except Exception as e:
        print("iobjectspy import failed:", e)
        return 1
    dump_class("iobjectspy.data", "Workspace")
    dump_class("iobjectspy.data", "Datasource")
    dump_class("iobjectspy.data", "DatasetVector")
    dump_class("iobjectspy.data", "DatasetGrid")
    dump_class("iobjectspy.mapping", "Map")
    dump_class("iobjectspy.mapping", "Layers")
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print("=" * 60)
        print("WORKSPACE PROBE:", path)
        try:
            from iobjectspy import Workspace
            ws = Workspace()
            ws.open(path)
            for attr in ("datasources", "maps"):
                try:
                    coll = getattr(ws, attr)
                    print("ws.%s -> type=%s" % (attr, type(coll)))
                    try:
                        print("   len:", len(coll))
                    except Exception:
                        pass
                    try:
                        first = coll[0]
                        print("   [0] type=%s repr=%r" % (type(first), first))
                    except Exception as e:
                        print("   [0] failed:", e)
                except Exception as e:
                    print("ws.%s failed: %s" % (attr, e))
            ws.close()
        except Exception as e:
            print("workspace probe failed:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
