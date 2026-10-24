# -*- coding: utf-8 -*-
"""
probe_api.py — arcpy 校准探针（只读，Python 2.7 / 3.x 兼容）
用途：首次部署或版本变更时运行一次，输出本机 arcpy 的版本与安装信息、
arcpy.mapping 的关键函数清单，以及 MapDocument("CURRENT") 在当前进程
是否可用（判断实时桥能否接入当前会话），供维护者据此收紧桥接脚本。
输出为多行文本（非 JSON），请完整回传，不要删减。
可选参数：传入一个 .mxd 路径时，额外以文件方式打开并盘点数据框/图层计数。
"""
from __future__ import print_function

import sys

try:
    _text = unicode  # noqa: F821  Python 2.7
except NameError:
    _text = str


def _u(v):
    if isinstance(v, _text):
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    try:
        return _text(v)
    except Exception:
        return repr(v)


def out(text=""):
    line = _u(text) + "\n"
    try:
        sys.stdout.write(line)
    except Exception:
        try:
            sys.stdout.write(line.encode("utf-8", "replace"))
        except Exception:
            pass
    try:
        sys.stdout.flush()
    except Exception:
        pass


def main():
    out("python: %s (%s)" % (sys.version.split()[0], sys.executable))
    try:
        import arcpy
    except Exception as e:
        out("arcpy import failed: %s" % e)
        out("提示：请用 ArcMap Desktop 自带的 Python 2.7 运行本探针，"
            "路径形如 C:\\Python27\\ArcGIS10.x\\python.exe")
        return 1
    out("arcpy file: %s" % getattr(arcpy, "__file__", "unknown"))
    try:
        info = arcpy.GetInstallInfo()
        for key in ("ProductName", "Version", "InstallDir", "InstallType"):
            if key in info:
                out("install %s: %s" % (key, info[key]))
    except Exception as e:
        out("GetInstallInfo failed: %s" % e)
    out("=" * 60)
    out("arcpy.mapping key names:")
    try:
        names = [n for n in dir(arcpy.mapping)
                 if n.startswith(("List", "Export", "MapDocument", "Refresh"))]
        for n in sorted(names):
            out("  - %s" % n)
    except Exception as e:
        out("  <unavailable: %s>" % e)
    out("=" * 60)
    out('MapDocument("CURRENT") probe（仅在 ArcMap Python 窗口内有意义）:')
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        out("  CURRENT available, filePath=%s" % getattr(mxd, "filePath", None))
        del mxd
    except Exception as e:
        out("  CURRENT unavailable in this process: %s" % e)
    if len(sys.argv) > 1:
        path = sys.argv[1]
        out("=" * 60)
        out("MXD PROBE: %s" % path)
        try:
            mxd = arcpy.mapping.MapDocument(path)
            for df in arcpy.mapping.ListDataFrames(mxd):
                layers = arcpy.mapping.ListLayers(mxd, "", df)
                out("  dataFrame %r: %d layers" % (df.name, len(layers)))
                for ly in layers:
                    out("    - %r visible=%s broken=%s"
                        % (ly.name, getattr(ly, "visible", None),
                           getattr(ly, "isBroken", None)))
            del mxd
        except Exception as e:
            out("  mxd probe failed: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
