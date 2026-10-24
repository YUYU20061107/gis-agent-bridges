# -*- coding: utf-8 -*-
"""
probe_api.py — fmeobjects API 校准探针（只读）
用途：首次部署或 FME 版本变更时运行一次，输出本机 fmeobjects 的真实形态：
模块位置、版本线索、FMEWorkspaceRunner 的方法清单，以及 FME 安装候选目录
的存在情况，供维护者据此收紧桥接脚本。
输出为多行文本（非 JSON），请完整回传，不要删减。
注意：探针只做导入与内省，不实例化 runner、不运行任何 workspace。
"""
import glob
import io
import os
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


def dump_class(mod, cls_name):
    print("=" * 60)
    print("CLASS fmeobjects.%s" % cls_name)
    cls = getattr(mod, cls_name, None)
    if cls is None:
        print("  <missing>")
        return
    for n in sorted(n for n in dir(cls) if not n.startswith("_")):
        print("  - %s" % n)


def main():
    print("python:", sys.version.split()[0])
    print("FME_HOME env:", os.environ.get("FME_HOME"))
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for d in sorted(glob.glob(os.path.join(base, "FME*"))):
            print("install candidate:", d, "(dir)" if os.path.isdir(d) else "")
    try:
        import fmeobjects
    except Exception as e:
        print("fmeobjects import failed:", e)
        print("hint: 用 FME 自带 Python 或把 FME 安装目录加入 sys.path 后重试；"
              "不要 pip 安装来历不明的同名包")
        return 1
    print("fmeobjects file:", getattr(fmeobjects, "__file__", "unknown"))
    for attr in ("__version__", "version", "VERSION"):
        v = getattr(fmeobjects, attr, None)
        if v:
            print("fmeobjects.%s: %s" % (attr, v))
    tops = [n for n in dir(fmeobjects) if not n.startswith("_")]
    print("fmeobjects top-level names:", ", ".join(tops))
    dump_class(fmeobjects, "FMEWorkspaceRunner")
    dump_class(fmeobjects, "FMEException")
    return 0


if __name__ == "__main__":
    sys.exit(main())
