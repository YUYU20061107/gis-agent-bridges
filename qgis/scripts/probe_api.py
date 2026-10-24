# -*- coding: utf-8 -*-
"""
probe_api.py — PyQGIS API 校准探针（只读）
用途：首次部署或版本变更时运行一次，输出本机 qgis 模块的版本、关键类的真实
方法清单，以及当前进程里 iface / processing 的可用性，供维护者据此收紧桥接脚本。
可选参数：一个工程文件路径（.qgs/.qgz），给出时会用 QgsApplication 无头打开
并回报图层形态。
输出为多行文本（非 JSON），请完整回传，不要删减。
qgis 模块一律惰性导入：无 QGIS 的机器上运行会如实打印导入失败并以退出码 1 结束。
"""
import io
import os
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
    print("python:", sys.version.split()[0])
    try:
        import qgis
        print("qgis module file:", getattr(qgis, "__file__", "unknown"))
        from qgis.core import Qgis
        print("QGIS version:", getattr(Qgis, "QGIS_VERSION", "unknown"))
        print("QGIS release:", getattr(Qgis, "QGIS_RELEASE_NAME", "unknown"))
    except Exception as e:
        print("qgis import failed:", e)
        return 1
    # iface 只在 QGIS GUI / Python 控制台进程内才有值；外部解释器里通常为 None
    try:
        from qgis.utils import iface
        print("iface in this process:", repr(iface))
    except Exception as e:
        print("iface probe failed:", e)
    # processing 插件可用性（控制台内通常已加载；无头脚本需 initialize）
    try:
        import processing
        print("processing module: available, run=%s" % hasattr(processing, "run"))
    except Exception as e:
        print("processing module: unavailable (%s)" % e)
    dump_class("qgis.core", "QgsProject")
    dump_class("qgis.core", "QgsApplication")
    dump_class("qgis.core", "QgsMapLayer")
    dump_class("qgis.core", "QgsVectorLayer")
    dump_class("qgis.core", "QgsLayoutExporter")
    dump_class("qgis.core", "QgsLayerTreeLayer")
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print("=" * 60)
        print("PROJECT PROBE:", path)
        try:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from qgis.core import QgsApplication, QgsProject
            app = QgsApplication([], False)
            app.initQgis()
            try:
                project = QgsProject.instance()
                print("read ok:", project.read(path))
                print("title:", project.title())
                print("crs:", project.crs().authid())
                for layer in project.mapLayers().values():
                    print("  layer: name=%r type=%s source=%r crs=%s valid=%s"
                          % (layer.name(), layer.type(), layer.source(),
                             layer.crs().authid(), layer.isValid()))
                try:
                    root = project.layerTreeRoot()
                    print("layer tree children:",
                          [c.name() for c in root.children()])
                except Exception as e:
                    print("layer tree probe failed:", e)
                try:
                    print("layouts:", [lay.name() for lay in
                                       project.layoutManager().layouts()])
                except Exception as e:
                    print("layouts probe failed:", e)
            finally:
                app.exitQgis()
        except Exception as e:
            print("project probe failed:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
