# -*- coding: utf-8 -*-
"""
probe_api.py — arcpy API 校准/兼容性探针（只读，GeoScene 版）
用途：首次部署或 GeoScene Pro 版本变更时运行一次，输出本机 arcpy 的真实版本、
许可信息、arcpy.mp 关键类的真实方法清单，并实测 ArcGISProject("CURRENT")
在当前进程里是否可用（只有在 GeoScene Pro 进程内的 Python 窗口/Notebook 里
才预期可用，外部进程里不可用是预期结果，探针会如实记录，不算失败）。
【本探针的首要任务是产品身份核验】GeoScene 与 ArcGIS 共用 arcpy 内核：
必须先看下方 PRODUCT CLUE 两行（GetInstallInfo 的 ProductName / InstallDir
原文），确认当前 arcpy 属于 GeoScene 而非 Esri ArcGIS，再谈其余兼容性结论。
可选参数：一个 .aprx 路径，给出时打开并输出地图/布局的真实形态。
输出为多行文本（非 JSON），请完整回传，不要删减。
"""
import io
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


def dump_class(mp, cls_name):
    print("=" * 60)
    print("CLASS arcpy.mp.%s" % cls_name)
    cls = getattr(mp, cls_name, None)
    if cls is None:
        print("  <unavailable: arcpy.mp 无此类>")
        return
    names = [n for n in dir(cls) if not n.startswith("_")]
    for n in names:
        print("  - %s" % n)


def main():
    try:
        import arcpy
        print("arcpy file:", getattr(arcpy, "__file__", "unknown"))
        try:
            info = arcpy.GetInstallInfo()
            print("install info:", info)
            if isinstance(info, dict):
                print("PRODUCT CLUE ProductName:", info.get("ProductName"))
                print("PRODUCT CLUE InstallDir:", info.get("InstallDir"))
                print("PRODUCT CLUE Version:", info.get("Version"))
                print("PRODUCT CLUE LicenseLevel:", info.get("LicenseLevel"))
        except Exception as e:
            print("GetInstallInfo failed:", e)
        try:
            print("product info:", arcpy.ProductInfo())
        except Exception as e:
            print("ProductInfo failed:", e)
    except Exception as e:
        print("arcpy import failed:", e)
        return 1
    try:
        from arcpy import mp
    except Exception as e:
        print("arcpy.mp import failed:", e)
        return 1
    for cls_name in ("ArcGISProject", "Map", "Layer", "Table", "Layout", "MapFrame"):
        dump_class(mp, cls_name)
    print("=" * 60)
    print('CURRENT PROBE: ArcGISProject("CURRENT") in this process')
    try:
        cur = mp.ArcGISProject("CURRENT")
        print("  CURRENT available ->", cur.filePath if cur is not None else None)
    except Exception as e:
        print("  CURRENT not available in this process: %s" % e)
        print("  （外部进程里不可用是预期结果；请在 GeoScene Pro 的 Python 窗口/Notebook 里重跑探针）")
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print("=" * 60)
        print("PROJECT PROBE:", path)
        try:
            aprx = mp.ArcGISProject(path)
            print("  filePath:", aprx.filePath)
            try:
                print("  defaultGeodatabase:", aprx.defaultGeodatabase)
            except Exception as e:
                print("  defaultGeodatabase failed:", e)
            for m in aprx.listMaps():
                layers = m.listLayers()
                tables = m.listTables()
                print("  MAP %r layers=%d tables=%d" % (m.name, len(layers), len(tables)))
                for ly in layers[:10]:
                    print("    layer %r type=%s" % (getattr(ly, "name", None), type(ly)))
            for lo in aprx.listLayouts():
                print("  LAYOUT %r page=%sx%s" % (lo.name,
                                                  getattr(lo, "pageWidth", None),
                                                  getattr(lo, "pageHeight", None)))
                try:
                    print("    mapframes:", len(lo.listElements("MAPFRAME_ELEMENT")))
                except Exception as e:
                    print("    listElements failed:", e)
        except Exception as e:
            print("  project probe failed:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
