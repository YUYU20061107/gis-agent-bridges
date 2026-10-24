# -*- coding: utf-8 -*-
"""
inapp_bridge.py — QGIS 应用内实时桥（v0.2）

运行位置：QGIS 的 Python 控制台内（不是外部命令行）。
作用：在本机 127.0.0.1:47618 开一个行分隔 JSON 的 TCP 服务，
外部的 MCP 服务端（mcp_server.py）把工具调用转发进来，
桥在 QGIS 的 Python 会话里执行，操作当前打开的工程。

安全：
  - 只监听 127.0.0.1；每次启动生成随机 token，写入 ~/.qgis-live-bridge.token
    （可用环境变量 QGIS_BRIDGE_TOKEN_FILE 覆盖位置，MCP 侧同名变量须一致），
    请求必须带对 token，否则拒绝。
  - 写/执行类工具（add_layer_from_path / run_processing / save_project）
    需要 args.confirm == true 才执行；视图级操作（set_layer_visible /
    zoom_to_layer）不设闸，但只改显示状态、可逆，风险等级见 LIVE.md。
  - 刻意不提供任意代码执行工具：run_processing 只接受算法 id + 参数 JSON，
    这是有意的安全取舍，不许临时加 exec/eval 类工具绕过。

当前工程的获取方式因 QGIS 版本/控制台注入方式而异，本脚本用多策略发现：
  1) 控制台注入的全局变量（iface / project / qgs_project 等）
  2) qgis.utils.iface（控制台初始化后模块属性）+ QgsProject.instance()
  3) 直接 QgsProject.instance()
  4) 文件回退：环境变量 QGIS_LIVE_PROJECT_PATH 指向的 .qgs/.qgz，
     仅解析文件做只读盘点（mode=file-fallback，不能假装是实时对象，
     视图/写类工具在该模式下返回 NOT_SUPPORTED）
discover 工具会把发现过程与现场对象的方法清单一并回报，供维护者据实收紧策略。

线程模型（待实机校准）：QGIS 的 Qt 对象原则上只能在 GUI 主线程触碰，而 socket
服务跑在后台线程。本桥多策略处理：若能拿到 qgis.PyQt.QtCore.QTimer，
就在启动时（exec 发生在控制台主线程）建一个主线程调度器，后台线程把工具
执行投递回主线程跑；拿不到 Qt 就退化为工作线程直执（discover 会如实回报
dispatch 字段）。两种路径哪种在目标版本上稳定，必须实机校准后定案。

qgis 模块一律惰性导入：没有 QGIS 的机器上本文件也能被 MCP 自检拉起，
此时 discover 结构化回报 project_found=false。

单文件约束：本文件必须能被 QGIS Python 控制台单文件 exec 运行，无法 import
同包模块，因此工程 XML 解析逻辑以内联副本形式维护（与 scripts/qgis_bridge.py
的解析实现保持一致口径，改一侧需同步另一侧）。

全部实时工具均未在真实 QGIS 上验证，首次实机使用须按 docs/CALIBRATION.md
的顺序校准。
"""
import json
import os
import queue
import socket
import sys
import threading
import traceback
import uuid
import xml.etree.ElementTree as ET
import zipfile

HOST = "127.0.0.1"
PORT = 47618
# token 文件位置可用 QGIS_BRIDGE_TOKEN_FILE 覆盖（MCP 侧同名变量须一致）
TOKEN_FILE = os.environ.get("QGIS_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".qgis-live-bridge.token")
TOKEN = uuid.uuid4().hex

_state = {"project": None, "iface": None, "mode": None,
          "attempts": [], "inventory": None, "dispatch": "worker-thread"}


# ---------------------------------------------------------------- 惰性导入
def _import_qgis_core():
    from qgis.core import QgsProject  # noqa: F401
    import qgis.core as core
    return core


def _qgis_version():
    try:
        from qgis.core import Qgis
        return getattr(Qgis, "QGIS_VERSION", "unknown")
    except Exception:
        return None


def _get_iface():
    """多策略拿 iface：注入全局 → qgis.utils.iface。"""
    import __main__
    for scope in (globals(), vars(__main__)):
        obj = scope.get("iface")
        if obj is not None:
            return obj
    try:
        from qgis.utils import iface
        return iface
    except Exception:
        return None


# ------------------------------------------------------------- 通用调用助手
def _call_first(obj, method_names, arg_variants, notes):
    """依次尝试 方法名 × 参数组合，返回 (结果, "方法/参数个数")；全失败 (None, None)。"""
    for name in method_names:
        fn = getattr(obj, name, None)
        if not callable(fn):
            continue
        for av in arg_variants:
            try:
                return fn(*av), "%s/%d" % (name, len(av))
            except Exception as e:
                notes.append("%s(args=%d) failed: %s" % (name, len(av), e))
    return None, None


def _methods_hint(obj, limit=120):
    try:
        return [n for n in dir(obj) if not n.startswith("_")][:limit]
    except Exception:
        return []


def _safe_str(v):
    try:
        return str(v)
    except Exception:
        return None


# ------------------------------------------------- 文件回退：工程 XML 解析
def _text(elem, tag):
    child = elem.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _parse_project_file(path):
    """解析 .qgs/.qgz 得到只读盘点（与 scripts/qgis_bridge.py 同口径的内联副本）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".qgz":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".qgs")]
            if not names:
                raise ValueError(".qgz 内未找到 .qgs 成员")
            data = z.read(names[0])
    else:
        with open(path, "rb") as f:
            data = f.read()
    root = ET.fromstring(data)
    layers = []
    for ml in root.iter("maplayer"):
        crs = None
        for sub in ml.iter():
            if sub.tag in ("srs", "crs"):
                auth = sub.find(".//authid")
                if auth is not None and auth.text:
                    crs = auth.text.strip()
                    break
        prov = ml.find("provider")
        layers.append({"id": _text(ml, "id"), "name": _text(ml, "layername"),
                       "type": ml.get("type"),
                       "datasource": _text(ml, "datasource"),
                       "provider": (prov.text.strip()
                                    if prov is not None and prov.text else None),
                       "crs_authid": crs})
    canvas_crs = None
    dest = root.find(".//destinationsrs")
    if dest is not None:
        auth = dest.find(".//authid")
        if auth is not None and auth.text:
            canvas_crs = auth.text.strip()
    return {"title": _text(root, "title") or root.get("projectname"),
            "file_path": path, "canvas_crs_authid": canvas_crs,
            "layers": layers,
            "layouts": [el.get("name") for el in root.iter("Layout")
                        if el.get("name")]}


# ------------------------------------------------------------- 工程发现
def _looks_like_project(obj):
    return obj is not None and callable(getattr(obj, "mapLayers", None))


def discover_project(force=False):
    """多策略发现当前工程；返回 (project, mode, attempts)。"""
    if _state["project"] is not None and not force:
        return _state["project"], _state["mode"], _state["attempts"]
    attempts = []
    _state["inventory"] = None
    # 策略 1：注入的全局变量
    import __main__
    for scope_name, scope in (("bridge_globals", globals()), ("__main__", vars(__main__))):
        for key in ("project", "qgs_project", "current_project", "qgsProject"):
            obj = scope.get(key)
            if _looks_like_project(obj):
                attempts.append("accepted %s.%s" % (scope_name, key))
                _state.update(project=obj, iface=_get_iface(),
                              mode="live:" + scope_name + "." + key,
                              attempts=attempts)
                return obj, _state["mode"], attempts
    iface = _get_iface()
    _state["iface"] = iface
    # 策略 2/3：QgsProject.instance()（有 iface 时标注 live:iface）
    try:
        core = _import_qgis_core()
        project = core.QgsProject.instance()
        if _looks_like_project(project):
            mode = "live:iface" if iface is not None else "live:qgsproject-instance"
            attempts.append("accepted QgsProject.instance() (iface=%s)"
                            % (iface is not None))
            _state.update(project=project, mode=mode, attempts=attempts)
            return project, mode, attempts
        attempts.append("QgsProject.instance() returned unusable object")
    except Exception as e:
        attempts.append("QgsProject.instance() failed: %s" % e)
    # 策略 4：文件回退（只读盘点）
    path = os.environ.get("QGIS_LIVE_PROJECT_PATH")
    if path and os.path.isfile(path):
        try:
            _state["inventory"] = _parse_project_file(path)
            attempts.append("file-fallback parsed %s" % path)
            _state.update(project=None, mode="file-fallback", attempts=attempts)
            return None, "file-fallback", attempts
        except Exception as e:
            attempts.append("file-fallback parse failed: %s" % e)
    _state.update(project=None, mode=None, attempts=attempts)
    return None, None, attempts


def _require_project():
    project, mode, attempts = discover_project()
    if mode == "file-fallback":
        raise RuntimeError("NOT_SUPPORTED: 当前为 file-fallback 模式（只有文件盘点，"
                           "无实时工程对象），本工具不可用")
    if project is None:
        raise RuntimeError("LIVE_PROJECT_NOT_FOUND: 未发现当前工程；attempts=%s"
                           % attempts)
    return project, mode


def _project_and_mode():
    project, mode, _a = discover_project()
    return project, mode


# ------------------------------------------------------- Qt 主线程调度器
class _QtDispatcher(object):
    """把工具执行投递回 Qt 主线程（QTimer 在 exec 的主线程里创建）。"""

    def __init__(self):
        from qgis.PyQt.QtCore import QTimer
        self._queue = queue.Queue()
        self._timer = QTimer()
        self._timer.timeout.connect(self._pump)
        self._timer.start(50)

    def _pump(self):
        while True:
            try:
                fn, box = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                box["result"] = fn()
            except Exception as e:  # noqa: BLE001 - 原样回传给等待线程
                box["error"] = e
            box["event"].set()

    def run(self, fn, timeout=60):
        box = {"event": threading.Event()}
        self._queue.put((fn, box))
        if not box["event"].wait(timeout):
            raise RuntimeError("QT_DISPATCH_TIMEOUT: 主线程调度超时（GUI 可能被弹窗阻塞）")
        if "error" in box:
            raise box["error"]
        return box.get("result")


_dispatcher = None


def _execute(fn):
    if _dispatcher is not None and threading.current_thread() is not threading.main_thread():
        return _dispatcher.run(fn)
    return fn()


def _init_dispatcher():
    global _dispatcher
    try:
        _dispatcher = _QtDispatcher()
        _state["dispatch"] = "qt-main-thread"
    except Exception:
        _dispatcher = None
        _state["dispatch"] = "worker-thread"


# ------------------------------------------------------------- 图层定位
def _layer_entry_live(layer, node_visible=None):
    entry = {"id": None, "name": None, "type": None,
             "class": type(layer).__name__, "datasource": None,
             "crs_authid": None, "valid": None, "visible": node_visible}
    for attr, key in (("id", "id"), ("name", "name"), ("source", "datasource")):
        try:
            entry[key] = getattr(layer, attr)()
        except Exception:
            pass
    try:
        entry["type"] = str(layer.type())
    except Exception:
        pass
    try:
        entry["crs_authid"] = layer.crs().authid()
    except Exception:
        pass
    try:
        entry["valid"] = bool(layer.isValid())
    except Exception:
        pass
    return entry


def _node_visible(node, notes):
    """图层树节点显隐读取，多策略；返回 True/False/None。"""
    val, via = None, None
    for name in ("isVisible", "itemVisibilityChecked", "visibilityChecked"):
        fn = getattr(node, name, None)
        if callable(fn):
            try:
                val = fn()
                via = name
                break
            except Exception as e:
                notes.append("%s failed: %s" % (name, e))
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    # Qt::CheckState 枚举：Checked=2 / Unchecked=0 / PartiallyChecked=1
    try:
        iv = int(val)
        if iv == 2:
            return True
        if iv == 0:
            return False
        return None
    except Exception:
        return bool(val)


def _walk_layer_tree(node, path, out, notes):
    children = []
    try:
        children = list(node.children())
    except Exception:
        pass
    for child in children:
        layer = None
        try:
            layer = child.layer()
        except Exception:
            layer = None
        if layer is not None:
            entry = _layer_entry_live(layer, _node_visible(child, notes))
            entry["group"] = "/".join(path) if path else None
            out.append(entry)
        else:
            name = None
            try:
                name = child.name()
            except Exception:
                pass
            _walk_layer_tree(child, path + [name or ""], out, notes)


def _find_layer(project, selector):
    """selector 可为图层名、图层 id 或整数下标。返回 (layer, 全部图层名)。"""
    layers = list(project.mapLayers().values())
    names = []
    for i, layer in enumerate(layers):
        try:
            names.append(layer.name())
        except Exception:
            names.append(None)
        if isinstance(selector, int) and selector == i:
            return layer, names
    for layer in layers:
        try:
            if layer.id() == selector or layer.name() == selector:
                return layer, names
        except Exception:
            continue
    if isinstance(selector, str) and selector.isdigit():
        idx = int(selector)
        if 0 <= idx < len(layers):
            return layers[idx], names
    return None, names


# ------------------------------------------------------------ 只读工具
def tool_ping(args):
    return {"pong": True, "bridge": "qgis-live-bridge/0.2",
            "python": sys.version.split()[0], "dispatch": _state["dispatch"]}


def tool_discover(args):
    project, mode, attempts = discover_project(force=True)
    report = {"mode": mode, "attempts": attempts,
              "project_found": project is not None or mode == "file-fallback",
              "dispatch": _state["dispatch"],
              "qgis_version": _qgis_version(),
              "iface_available": _state.get("iface") is not None}
    if project is not None:
        report["project_type"] = str(type(project))
        report["project_methods"] = _methods_hint(project, 200)
        try:
            report["layer_count"] = len(project.mapLayers())
        except Exception:
            pass
    if _state.get("inventory") is not None:
        report["inventory_file"] = _state["inventory"].get("file_path")
    # processing 可用性（只探测，不初始化）
    try:
        import processing  # noqa: F401
        report["processing_available"] = True
    except Exception as e:
        report["processing_available"] = False
        report["processing_error"] = str(e)
    import __main__
    report["main_globals"] = [k for k in vars(__main__).keys()
                              if not k.startswith("_")][:100]
    return report


def tool_project_info(args):
    project, mode = _project_and_mode()
    if mode == "file-fallback":
        inv = _state.get("inventory") or {}
        return {"mode": mode, "title": inv.get("title"),
                "file_name": inv.get("file_path"),
                "canvas_crs_authid": inv.get("canvas_crs_authid"),
                "layer_count": len(inv.get("layers", [])),
                "layout_count": len(inv.get("layouts", [])),
                "note": "file-fallback：以上来自工程文件解析，非实时工程对象"}
    if project is None:
        raise RuntimeError("LIVE_PROJECT_NOT_FOUND: 未发现当前工程")
    info = {"mode": mode}
    for attr, key in (("title", "title"), ("fileName", "file_name"),
                      ("homePath", "home_path")):
        try:
            info[key] = getattr(project, attr)() or None
        except Exception:
            info[key] = None
    try:
        info["project_crs_authid"] = project.crs().authid()
    except Exception:
        info["project_crs_authid"] = None
    try:
        info["layer_count"] = len(project.mapLayers())
    except Exception:
        info["layer_count"] = None
    try:
        info["layout_count"] = len(project.layoutManager().layouts())
    except Exception:
        info["layout_count"] = None
    return info


def tool_list_layers(args):
    project, mode = _project_and_mode()
    if mode == "file-fallback":
        inv = _state.get("inventory") or {}
        return {"mode": mode, "via": "file-parse",
                "layers": inv.get("layers", []),
                "note": "file-fallback：来自工程文件解析，无显隐等实时状态"}
    if project is None:
        raise RuntimeError("LIVE_PROJECT_NOT_FOUND: 未发现当前工程")
    notes = []
    # 策略 A：图层树（带顺序/分组/显隐）
    try:
        root = project.layerTreeRoot()
        out = []
        _walk_layer_tree(root, [], out, notes)
        return {"mode": mode, "via": "layerTreeRoot", "layers": out,
                "notes": notes}
    except Exception as e:
        notes.append("layerTreeRoot strategy failed: %s" % e)
    # 策略 B：mapLayers 字典序
    out = [_layer_entry_live(ly) for ly in project.mapLayers().values()]
    return {"mode": mode, "via": "mapLayers", "layers": out, "notes": notes}


def tool_list_layouts(args):
    project, mode = _project_and_mode()
    if mode == "file-fallback":
        inv = _state.get("inventory") or {}
        return {"mode": mode, "via": "file-parse",
                "layouts": inv.get("layouts", [])}
    if project is None:
        raise RuntimeError("LIVE_PROJECT_NOT_FOUND: 未发现当前工程")
    manager = project.layoutManager()
    layouts, via = None, None
    layouts, via = _call_first(manager, ["layouts", "printLayouts"], [()], [])
    if layouts is None:
        raise RuntimeError("NOT_SUPPORTED: layoutManager 无 layouts 访问器；"
                           "manager_methods=%s" % _methods_hint(manager))
    names = []
    for lay in layouts:
        try:
            names.append(lay.name())
        except Exception:
            names.append(_safe_str(lay))
    return {"mode": mode, "via": via, "layouts": names}


def tool_list_fields(args):
    project, _mode = _require_project()
    selector = args.get("layer")
    if selector is None:
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名/id/下标）")
    layer, names = _find_layer(project, selector)
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s"
                           % (selector, names))
    fields_fn = getattr(layer, "fields", None)
    if not callable(fields_fn):
        raise RuntimeError("NOT_SUPPORTED: 该图层无 fields()（可能不是矢量图层）；"
                           "layer_methods=%s" % _methods_hint(layer))
    out = []
    for f in fields_fn():
        entry = {"name": None, "type": None, "length": None}
        for attr, key in (("name", "name"), ("typeName", "type"),
                          ("length", "length")):
            try:
                entry[key] = getattr(f, attr)()
            except Exception:
                pass
        out.append(entry)
    return {"layer": layer.name(), "fields": out}


# ------------------------------------------------------------ 视图级工具
def tool_set_layer_visible(args):
    """视图级：设置图层在图层树中的勾选显隐（只改显示状态、可逆）。"""
    project, mode = _require_project()
    selector = args.get("layer")
    visible = args.get("visible")
    if selector is None or not isinstance(visible, bool):
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名/id/下标）与 visible（布尔）")
    layer, names = _find_layer(project, selector)
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s"
                           % (selector, names))
    notes = []
    node = None
    try:
        node = project.layerTreeRoot().findLayer(layer.id())
    except Exception as e:
        notes.append("findLayer failed: %s" % e)
    if node is None:
        raise RuntimeError("NOT_SUPPORTED: 图层树中找不到该图层节点（可能未加入图层树）；"
                           "notes=%s" % notes)
    via = None
    for setter in ("setItemVisibilityChecked", "setVisibilityChecked"):
        fn = getattr(node, setter, None)
        if callable(fn):
            try:
                fn(visible)
                via = setter
                break
            except Exception as e:
                notes.append("%s failed: %s" % (setter, e))
    if via is None:
        raise RuntimeError("NOT_SUPPORTED: 图层树节点无显隐设置途径；notes=%s；"
                           "node_methods=%s" % (notes, _methods_hint(node)))
    refresh_via = None
    iface = _state.get("iface") or _get_iface()
    if iface is not None:
        try:
            iface.mapCanvas().refresh()
            refresh_via = "iface.mapCanvas().refresh"
        except Exception as e:
            notes.append("canvas refresh failed: %s" % e)
    return {"mode": mode, "layer": layer.name(), "visible_set_to": visible,
            "visible_now": _node_visible(node, notes), "via": via,
            "refresh_via": refresh_via, "notes": notes}


def tool_zoom_to_layer(args):
    """视图级：把画布缩放到图层范围。无 iface/画布时如实报 NOT_SUPPORTED 并附范围。"""
    project, mode = _require_project()
    selector = args.get("layer")
    if selector is None:
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名/id/下标）")
    layer, names = _find_layer(project, selector)
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s"
                           % (selector, names))
    extent = None
    try:
        e = layer.extent()
        extent = {"xmin": e.xMinimum(), "ymin": e.yMinimum(),
                  "xmax": e.xMaximum(), "ymax": e.yMaximum()}
    except Exception:
        extent = None
    iface = _state.get("iface") or _get_iface()
    if iface is None:
        raise RuntimeError("NOT_SUPPORTED: 无 iface/画布可缩放（extent=%s 已取得，"
                           "但没有实时画布）" % extent)
    notes = []
    canvas = iface.mapCanvas()
    via = None
    # 策略 1：setActiveLayer + actionZoomToLayer
    try:
        iface.setActiveLayer(layer)
        action = iface.actionZoomToLayer()
        action.trigger()
        via = "actionZoomToLayer"
    except Exception as e:
        notes.append("actionZoomToLayer failed: %s" % e)
    # 策略 2：canvas.setExtent(layer.extent()) + refresh
    if via is None:
        try:
            canvas.setExtent(layer.extent())
            canvas.refresh()
            via = "canvas.setExtent+refresh"
        except Exception as e:
            notes.append("canvas.setExtent failed: %s" % e)
    if via is None:
        raise RuntimeError("NOT_SUPPORTED: 范围已取得 %s，但缩放策略全失败；notes=%s"
                           % (extent, notes))
    return {"zoomed": True, "mode": mode, "layer": layer.name(), "via": via,
            "extent": extent, "notes": notes}


# ------------------------------------------------------------ 写/执行类工具
_VECTOR_EXTS = (".shp", ".geojson", ".json", ".gpkg", ".kml", ".gml", ".csv")
_RASTER_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".vrt", ".asc")


def tool_add_layer_from_path(args):
    """写类（内容级）：按路径加载图层并加入当前工程。须 confirm=true。"""
    if args.get("confirm") is not True:
        return {"added": False,
                "reason": "add_layer_from_path 需要 confirm=true 显式确认"}
    project, mode = _require_project()
    path = args.get("path")
    if not path or not os.path.isfile(path):
        raise RuntimeError("BAD_ARGS: path 必须是已存在的文件: %r" % path)
    name = args.get("name") or os.path.splitext(os.path.basename(path))[0]
    provider = args.get("provider")
    ext = os.path.splitext(path)[1].lower()
    if provider is None:
        provider = "ogr" if ext in _VECTOR_EXTS else "gdal"
    from qgis.core import QgsVectorLayer, QgsRasterLayer
    cls = QgsVectorLayer if provider == "ogr" else QgsRasterLayer
    layer = cls(path, name, provider)
    if not layer.isValid():
        # 矢量/栅格互换再试一次（如 .gpkg 里的栅格）
        other = QgsRasterLayer if cls is QgsVectorLayer else QgsVectorLayer
        other_provider = "gdal" if cls is QgsVectorLayer else "ogr"
        layer2 = other(path, name, other_provider)
        if layer2.isValid():
            layer, provider = layer2, other_provider
        else:
            detail = None
            try:
                detail = layer.error().summary()
            except Exception:
                pass
            raise RuntimeError("LAYER_LOAD_FAILED: 图层加载无效（%s, provider=%s）；"
                               "error=%s" % (path, provider, detail))
    before = len(project.mapLayers())
    notes = []
    via = None
    # 策略 1：QgsProject.addMapLayer
    try:
        project.addMapLayer(layer)
        via = "QgsProject.addMapLayer"
    except Exception as e:
        notes.append("addMapLayer failed: %s" % e)
    # 策略 2：iface 添加
    if via is None:
        iface = _state.get("iface") or _get_iface()
        if iface is not None:
            fn = (iface.addVectorLayer if provider == "ogr"
                  else iface.addRasterLayer)
            try:
                added = fn(path, name, provider)
                if added is not None:
                    layer, via = added, "iface.add*Layer"
            except Exception as e:
                notes.append("iface add failed: %s" % e)
    if via is None:
        raise RuntimeError("ADD_LAYER_FAILED: 图层已构造且有效，但加入工程失败；"
                           "notes=%s" % notes)
    return {"added": True, "mode": mode, "via": via, "provider": provider,
            "layer": _layer_entry_live(layer),
            "layers_before": before,
            "layers_after": len(project.mapLayers())}


def _serialize_processing_result(result):
    out = {}
    if not isinstance(result, dict):
        return {"result": _safe_str(result)}
    for k, v in result.items():
        if hasattr(v, "name") and hasattr(v, "source"):
            try:
                out[k] = {"layer_name": v.name(), "source": v.source()}
                continue
            except Exception:
                pass
        out[k] = _safe_str(v)
    return out


def tool_run_processing(args):
    """执行类：运行一个 Processing 算法。须 confirm=true。
    只接受 algorithm（算法 id，如 native:buffer）+ parameters（参数对象）；
    刻意不提供任意代码执行入口。参数由调用方负责，执行前请人工复核。"""
    if args.get("confirm") is not True:
        return {"ran": False,
                "reason": "run_processing 需要 confirm=true 显式确认"}
    _project, mode = _require_project()
    algorithm = args.get("algorithm")
    params = args.get("parameters") or {}
    if not algorithm or not isinstance(algorithm, str):
        raise RuntimeError("BAD_ARGS: 必须提供 algorithm（算法 id 字符串）")
    if not isinstance(params, dict):
        raise RuntimeError("BAD_ARGS: parameters 必须是 JSON 对象")
    run_fn = None
    via = None
    notes = []
    try:
        import processing
        if hasattr(processing, "run"):
            run_fn, via = processing.run, "import processing"
    except Exception as e:
        notes.append("import processing failed: %s" % e)
    if run_fn is None:
        try:
            from processing.tools import general
            if hasattr(general, "run"):
                run_fn, via = general.run, "processing.tools.general.run"
        except Exception as e:
            notes.append("processing.tools.general failed: %s" % e)
    if run_fn is None:
        raise RuntimeError("NOT_SUPPORTED: Processing 框架不可用（插件未加载？）；"
                           "notes=%s" % notes)
    result = run_fn(algorithm, params)
    return {"ran": True, "mode": mode, "via": via, "algorithm": algorithm,
            "result": _serialize_processing_result(result),
            "note": "输出图层若写入工程/磁盘以 result 为准，请用 list_layers 复核"}


def tool_export_map_image(args):
    """只读出文件：导出地图为图片到指定路径。多策略，以文件真实落盘为准。"""
    project, mode = _require_project()
    out_path = args.get("out_path")
    if not out_path:
        raise RuntimeError("BAD_ARGS: 必须提供 out_path（图片输出路径）")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(out_dir):
        raise RuntimeError("BAD_ARGS: 输出目录不存在: %s" % out_dir)
    notes = []

    def done(via):
        return {"exported": True, "mode": mode, "via": via, "path": out_path,
                "bytes": os.path.getsize(out_path)}

    # 策略 1：布局导出（指定 layout 时）
    layout_name = args.get("layout")
    if layout_name:
        try:
            from qgis.core import QgsLayoutExporter
            layout = project.layoutManager().layoutByName(layout_name)
            if layout is None:
                notes.append("layout %r not found" % layout_name)
            else:
                exporter = QgsLayoutExporter(layout)
                ok = False
                try:
                    settings = QgsLayoutExporter.ImageExportSettings()
                    if isinstance(args.get("dpi"), int):
                        settings.dpi = args["dpi"]
                    exporter.exportToImage(out_path, settings)
                    ok = True
                except Exception as e:
                    notes.append("exportToImage(settings) failed: %s" % e)
                    exporter.exportToImage(out_path)
                    ok = True
                if ok and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                    return done("QgsLayoutExporter.exportToImage")
                notes.append("layout export 未落盘")
        except Exception as e:
            notes.append("layout strategy failed: %s" % e)
    # 策略 2：画布 saveAsImage
    iface = _state.get("iface") or _get_iface()
    if iface is not None:
        try:
            iface.mapCanvas().saveAsImage(out_path)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return done("mapCanvas.saveAsImage")
            notes.append("saveAsImage 调用未报错但文件未落盘")
        except Exception as e:
            notes.append("saveAsImage failed: %s" % e)
    # 策略 3：QgsMapSettings + 顺序渲染任务（不需要 iface）
    try:
        from qgis.core import QgsMapSettings, QgsMapRendererSequentialJob
        from qgis.PyQt.QtCore import QSize
        from qgis.PyQt.QtGui import QImage
        settings = QgsMapSettings()
        layers = list(project.mapLayers().values())
        settings.setLayers(layers)
        if layers:
            extent = layers[0].extent()
            for ly in layers[1:]:
                extent.combineExtentWith(ly.extent())
            settings.setExtent(extent)
        width = args.get("width") if isinstance(args.get("width"), int) else 1024
        height = args.get("height") if isinstance(args.get("height"), int) else 768
        settings.setOutputSize(QSize(width, height))
        job = QgsMapRendererSequentialJob(settings)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()
        if not img.isNull() and img.save(out_path):
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return done("QgsMapRendererSequentialJob")
        notes.append("render job 未产出有效图片")
    except Exception as e:
        notes.append("render strategy failed: %s" % e)
    raise RuntimeError("NOT_SUPPORTED: 全部导出策略失败或未落盘；notes=%s" % notes)


def tool_save_project(args):
    """写类：保存当前工程。须 confirm=true。给了 path 则另存为该路径。"""
    if args.get("confirm") is not True:
        return {"saved": False,
                "reason": "save_project 需要 confirm=true 显式确认"}
    project, mode = _require_project()
    path = args.get("path")
    notes = []
    if path:
        ok, via = _call_first(project, ["write"], [(path,)], notes)
    else:
        ok, via = _call_first(project, ["write"], [()], notes)
    if via is None or ok is False:
        raise RuntimeError("SAVE_FAILED: 工程保存失败；notes=%s" % notes)
    file_name = None
    try:
        file_name = project.fileName() or None
    except Exception:
        pass
    return {"saved": True, "mode": mode, "via": via, "file_name": file_name}


TOOLS = {
    "ping": tool_ping,
    "discover": tool_discover,
    "project_info": tool_project_info,
    "list_layers": tool_list_layers,
    "list_layouts": tool_list_layouts,
    "list_fields": tool_list_fields,
    "set_layer_visible": tool_set_layer_visible,
    "zoom_to_layer": tool_zoom_to_layer,
    "add_layer_from_path": tool_add_layer_from_path,
    "run_processing": tool_run_processing,
    "export_map_image": tool_export_map_image,
    "save_project": tool_save_project,
}


def handle_request(req):
    if req.get("token") != TOKEN:
        return {"ok": False, "error": "BAD_TOKEN"}
    name = req.get("tool")
    fn = TOOLS.get(name)
    if fn is None:
        return {"ok": False, "error": "UNKNOWN_TOOL: %s" % name}
    try:
        return {"ok": True, "result": _execute(lambda: fn(req.get("args") or {}))}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                "traceback_tail": traceback.format_exc()[-600:]}


def serve():
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(TOKEN)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    print("[qgis-live-bridge] listening on %s:%d token_file=%s" % (HOST, PORT, TOKEN_FILE))
    print("[qgis-live-bridge] tools: %s" % ", ".join(sorted(TOOLS)))
    print("[qgis-live-bridge] dispatch: %s" % _state["dispatch"])
    sys.stdout.flush()
    while True:
        conn, _addr = srv.accept()
        with conn:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            if not buf.strip():
                continue
            try:
                req = json.loads(buf.decode("utf-8"))
            except Exception as e:
                resp = {"ok": False, "error": "BAD_JSON: %s" % e}
            else:
                resp = handle_request(req)
            conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))


def start(blocking=True):
    _init_dispatcher()
    if blocking:
        serve()
    else:
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        return t


if __name__ == "__main__":
    start(blocking=True)
else:
    # 在 QGIS Python 控制台里被 exec 时：起后台线程，不阻塞控制台
    start(blocking=False)
