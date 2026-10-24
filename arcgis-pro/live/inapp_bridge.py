# -*- coding: utf-8 -*-
"""
inapp_bridge.py — ArcGIS Pro 应用内实时桥（v0.2）

运行位置：ArcGIS Pro 的 Python 窗口或 Notebook 内（不是外部命令行）。
作用：在本机 127.0.0.1:47616 开一个行分隔 JSON 的 TCP 服务，
外部的 MCP 服务端（mcp_server.py）把工具调用转发进来，
桥在 Pro 的 Python 会话里执行，操作当前打开的工程，界面实时可见。

安全：
  - 只监听 127.0.0.1；每次启动生成随机 token，
    写入 ~/.arcgis-pro-live-bridge.token（可用环境变量 ARCGIS_PRO_BRIDGE_TOKEN_FILE 覆盖该路径），请求必须带对 token，否则拒绝。
  - 内容级写工具（add_layer_from_path / save_project）需要 args.confirm == true
    才执行；视图级操作（set_layer_visible / zoom_to_layer / set_labels_visible）
    不设闸，但只改显示状态、可逆，风险等级见 LIVE.md。
  - 工具面刻意收窄：不提供任意代码执行、任意 GP 工具调用类工具。这是有意取舍。

当前工程的获取方式用多策略发现：
  1) arcpy.mp.ArcGISProject("CURRENT") —— Pro 进程内的标准做法，mode=live:CURRENT
  2) Python 窗口注入的全局变量（project / current_project / aprx 等，须能 listMaps）
  3) 文件回退：环境变量 ARCPRO_LIVE_PROJECT_PATH 指向的 .aprx（经 arcpy.mp 打开；
     只能看到存盘状态，结果里标注 mode=file-fallback，不能假装是实时对象）
discover 工具会把发现过程与现场类的方法清单一并回报，供维护者据实收紧策略。

实验性说明（v0.2 全部工具均未在真实 ArcGIS Pro 上校准）：
  - 缩放走活动视图：aprx.activeView.camera.setExtent(extent)，
    extent 经 arcpy.Describe(layer) 取得；备用策略为 camera.extent 属性赋值。
  - 图层标注走 Layer.showLabels 属性；备用策略为 CIM 定义
    （layer.getDefinition('V3') 修改后 setDefinition 回写）。
  - 导出图片走 Layout.exportToPNG / MapFrame.exportToPNG。
  上述 API 的真实形态因 Pro 版本而异，桥内一律多策略尝试并回报命中策略（via 字段）；
  拿不到对象或 API 不匹配时返回结构化错误（NOT_SUPPORTED / *_FAILED，
  附现场方法清单线索），绝不假装成功。首次实机使用须按 docs/CALIBRATION.md 校准。
  另注：桥在后台线程里调用 arcpy.mp，若实机出现线程相关异常，按 CALIBRATION.md
  记录回报，不要在实机临时改架构。

单文件约束：本文件必须能被 Pro 的 Python 窗口单文件 exec 运行，无法 import 同包模块，
所有逻辑自包含。
"""
import json
import os
import socket
import sys
import threading
import traceback
import uuid

HOST = "127.0.0.1"
PORT = 47616
# token 文件位置可用 ARCGIS_PRO_BRIDGE_TOKEN_FILE 覆盖（受限环境里 ~ 可能不可写）；MCP 侧同名变量
TOKEN_FILE = os.environ.get("ARCGIS_PRO_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".arcgis-pro-live-bridge.token")
TOKEN = uuid.uuid4().hex

_state = {"project": None, "mode": None, "attempts": []}
_mp_cache = {"module": None, "error": None, "tried": False}


def _get_mp():
    """懒导入 arcpy.mp（外部无 arcpy 环境时返回 (None, 错误文本)，不崩溃）。"""
    if not _mp_cache["tried"]:
        _mp_cache["tried"] = True
        try:
            from arcpy import mp as _mp
            _mp_cache["module"] = _mp
        except Exception as e:
            _mp_cache["error"] = str(e)
    return _mp_cache["module"], _mp_cache["error"]


# ------------------------------------------------------------ 通用调用助手
def _try_attrs(obj, names):
    """按顺序尝试属性/方法，返回 (值, 命中的名字)；属性 getter 抛错也兜底；
    取到的方法会自动调用（无参）。"""
    for name in names:
        if obj is None:
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        try:
            if callable(val):
                val = val()
            return val, name
        except Exception:
            continue
    return None, None


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


def _set_first(obj, setter_names, attr_names, value, notes):
    """先试 setter 方法，再试属性赋值；返回命中的途径或 None。"""
    _res, via = _call_first(obj, setter_names, [(value,)], notes)
    if via:
        return via
    for attr in attr_names:
        try:
            setattr(obj, attr, value)
            return "attr:%s" % attr
        except Exception as e:
            notes.append("setattr %s failed: %s" % (attr, e))
    return None


def _methods_hint(obj, limit=120):
    try:
        return [n for n in dir(obj) if not n.startswith("_")][:limit]
    except Exception:
        return []


def _safe_str(v):
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _to_list(coll):
    if coll is None:
        return []
    try:
        return list(coll)
    except Exception:
        pass
    try:
        return [coll[i] for i in range(len(coll))]
    except Exception:
        return []


# ------------------------------------------------------------ 工程发现
def _validate_project(obj):
    """能 listMaps 才认作工程对象；返回地图列表或 None。"""
    if obj is None:
        return None
    try:
        maps = obj.listMaps()
        return _to_list(maps)
    except Exception:
        return None


def discover_project(force=False):
    """多策略发现当前工程；返回 (project, mode, attempts)。"""
    if _state["project"] is not None and not force:
        return _state["project"], _state["mode"], _state["attempts"]
    attempts = []
    candidates = []
    mp, mp_err = _get_mp()
    if mp is None:
        attempts.append("arcpy.mp import failed: %s" % mp_err)
    else:
        # 策略 1：ArcGISProject("CURRENT")（Pro 进程内的标准做法）
        try:
            cur = mp.ArcGISProject("CURRENT")
            if cur is not None:
                candidates.append(("CURRENT", cur))
            else:
                attempts.append("ArcGISProject('CURRENT') returned None")
        except Exception as e:
            attempts.append("ArcGISProject('CURRENT') failed: %s" % e)
    # 策略 2：注入的全局变量（本模块 globals 与 __main__ globals 都查）
    import __main__
    for scope_name, scope in (("bridge_globals", globals()), ("__main__", vars(__main__))):
        for key in ("project", "current_project", "currentProject", "aprx"):
            obj = scope.get(key)
            if obj is not None:
                candidates.append(("%s.%s" % (scope_name, key), obj))
    for label, obj in candidates:
        if _validate_project(obj) is not None:
            mode = "live:CURRENT" if label == "CURRENT" else "live:global:" + label
            attempts.append("accepted %s (listMaps ok)" % label)
            _state.update(project=obj, mode=mode, attempts=attempts)
            return obj, mode, attempts
        attempts.append("rejected %s (listMaps unavailable)" % label)
    # 策略 3：文件回退（只能看到存盘状态，不是实时对象）
    path = os.environ.get("ARCPRO_LIVE_PROJECT_PATH")
    if path and mp is not None:
        if os.path.isfile(path):
            try:
                proj = mp.ArcGISProject(path)
                attempts.append("file-fallback opened %s" % path)
                _state.update(project=proj, mode="file-fallback", attempts=attempts)
                return proj, "file-fallback", attempts
            except Exception as e:
                attempts.append("file-fallback failed: %s" % e)
        else:
            attempts.append("file-fallback path not a file: %s" % path)
    _state.update(project=None, mode=None, attempts=attempts)
    return None, None, attempts


def _require_project():
    proj, mode, attempts = discover_project()
    if proj is None:
        raise RuntimeError("LIVE_PROJECT_NOT_FOUND: 未发现当前工程；attempts=%s" % attempts)
    return proj, mode


# ------------------------------------------------------------ 地图/图层定位
def _find_map(aprx, map_name):
    maps = _to_list(_try_attrs(aprx, ["listMaps"])[0])
    names = []
    for m in maps:
        nm, _ = _try_attrs(m, ["name"])
        names.append(_safe_str(nm))
        if map_name is not None and _safe_str(nm) == map_name:
            return m
    if map_name is None and maps:
        return maps[0]
    raise RuntimeError("MAP_NOT_FOUND: 地图 %r 不存在；可用地图: %s" % (map_name, names))


def _find_layer(map_obj, selector):
    """selector 可为图层名、整数下标或数字字符串下标。返回 (layer, index, 全部图层名)。"""
    if isinstance(selector, str) and selector.isdigit():
        selector = int(selector)
    layers = _to_list(_try_attrs(map_obj, ["listLayers"])[0])
    names = []
    found = (None, None)
    for i, ly in enumerate(layers):
        if ly is None:
            names.append(None)
            continue
        nm, _ = _try_attrs(ly, ["name"])
        nm = _safe_str(nm)
        names.append(nm)
        if isinstance(selector, int) and selector == i:
            found = (ly, i)
        elif isinstance(selector, str) and nm == selector:
            found = (ly, i)
    return found[0], found[1], names


def _layer_entry(layer, index):
    entry = {"index": index}
    nm, _ = _try_attrs(layer, ["name"])
    entry["name"] = _safe_str(nm)
    grp, _ = _try_attrs(layer, ["isGroupLayer"])
    entry["is_group_layer"] = grp if isinstance(grp, bool) else None
    vis, _ = _try_attrs(layer, ["visible"])
    entry["visible"] = vis if isinstance(vis, bool) else None
    broken, _ = _try_attrs(layer, ["isBroken"])
    entry["is_broken"] = broken if isinstance(broken, bool) else None
    labels, _ = _try_attrs(layer, ["showLabels"])
    entry["show_labels"] = labels if isinstance(labels, bool) else None
    ds = None
    supports = getattr(layer, "supports", None)
    if callable(supports):
        try:
            if supports("DATASOURCE"):
                ds, _via = _try_attrs(layer, ["dataSource"])
        except Exception:
            ds = None
    if ds is None:
        ds, _via = _try_attrs(layer, ["dataSource"])
    entry["data_source"] = _safe_str(ds)
    return entry


# ------------------------------------------------------------ 只读工具
def tool_ping(args):
    return {"pong": True, "bridge": "arcgis-pro-live-bridge/0.2",
            "python": sys.version.split()[0]}


def tool_discover(args):
    proj, mode, attempts = discover_project(force=True)
    report = {"mode": mode, "attempts": attempts, "project_found": proj is not None}
    mp, mp_err = _get_mp()
    report["arcpy_mp_error"] = mp_err
    if mp is not None:
        report["mp_class_methods"] = {}
        for cls_name in ("ArcGISProject", "Map", "Layer", "Table", "Layout", "MapFrame"):
            cls = getattr(mp, cls_name, None)
            report["mp_class_methods"][cls_name] = _methods_hint(cls, 200) if cls else None
    try:
        import arcpy
        info = arcpy.GetInstallInfo()
        if isinstance(info, dict):
            report["arcgis_version"] = info.get("Version")
            report["license_level"] = info.get("LicenseLevel")
    except Exception as e:
        report["arcpy_error"] = str(e)
    if proj is not None:
        fp, _ = _try_attrs(proj, ["filePath"])
        report["project_file"] = _safe_str(fp)
        maps = _validate_project(proj)
        report["map_names"] = [_safe_str(_try_attrs(m, ["name"])[0]) for m in (maps or [])]
    import __main__
    report["main_globals"] = [k for k in vars(__main__).keys()
                              if not k.startswith("_")][:100]
    return report


def tool_project_info(args):
    proj, mode = _require_project()
    fp, _ = _try_attrs(proj, ["filePath"])
    dgdb, _ = _try_attrs(proj, ["defaultGeodatabase"])
    home, _ = _try_attrs(proj, ["homeFolder"])
    maps = _to_list(_try_attrs(proj, ["listMaps"])[0])
    layouts = _to_list(_try_attrs(proj, ["listLayouts"])[0])
    return {"mode": mode, "file_path": _safe_str(fp),
            "default_geodatabase": _safe_str(dgdb), "home_folder": _safe_str(home),
            "map_count": len(maps), "layout_count": len(layouts)}


def tool_list_maps(args):
    proj, mode = _require_project()
    out = []
    for m in _to_list(_try_attrs(proj, ["listMaps"])[0]):
        if m is None:
            continue
        nm, _ = _try_attrs(m, ["name"])
        mt, _ = _try_attrs(m, ["mapType"])
        out.append({"name": _safe_str(nm), "map_type": _safe_str(mt)})
    return {"mode": mode, "maps": out}


def tool_list_layers(args):
    proj, mode = _require_project()
    map_obj = _find_map(proj, args.get("map"))
    layers = _to_list(_try_attrs(map_obj, ["listLayers"])[0])
    return {"mode": mode,
            "map": _safe_str(_try_attrs(map_obj, ["name"])[0]),
            "layers": [_layer_entry(ly, i) for i, ly in enumerate(layers)
                       if ly is not None]}


def tool_list_tables(args):
    proj, mode = _require_project()
    map_obj = _find_map(proj, args.get("map"))
    out = []
    for t in _to_list(_try_attrs(map_obj, ["listTables"])[0]):
        if t is None:
            continue
        nm, _ = _try_attrs(t, ["name"])
        ds, _ = _try_attrs(t, ["dataSource"])
        broken, _ = _try_attrs(t, ["isBroken"])
        out.append({"name": _safe_str(nm), "data_source": _safe_str(ds),
                    "is_broken": broken if isinstance(broken, bool) else None})
    return {"mode": mode,
            "map": _safe_str(_try_attrs(map_obj, ["name"])[0]), "tables": out}


def tool_list_layouts(args):
    proj, mode = _require_project()
    out = []
    for lo in _to_list(_try_attrs(proj, ["listLayouts"])[0]):
        if lo is None:
            continue
        nm, _ = _try_attrs(lo, ["name"])
        pw, _ = _try_attrs(lo, ["pageWidth"])
        ph, _ = _try_attrs(lo, ["pageHeight"])
        frames = None
        try:
            frames = lo.listElements("MAPFRAME_ELEMENT")
        except Exception:
            frames = None
        out.append({"name": _safe_str(nm),
                    "page_width": pw if isinstance(pw, (int, float)) else None,
                    "page_height": ph if isinstance(ph, (int, float)) else None,
                    "map_frame_count": len(_to_list(frames)) if frames is not None else None})
    return {"mode": mode, "layouts": out}


# ------------------------------------------------------------ 视图级工具（实验性）
def tool_set_layer_visible(args):
    """视图级：设置图层显隐。多策略：visible 属性 → CIM definition 回写（待实机校准）。"""
    proj, mode = _require_project()
    selector = args.get("layer")
    visible = args.get("visible")
    if selector is None or not isinstance(visible, bool):
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名或下标）与 visible（布尔）")
    map_obj = _find_map(proj, args.get("map"))
    layer, idx, names = _find_layer(map_obj, selector)
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s" % (selector, names))
    notes = []
    via = _set_first(layer, [], ["visible"], visible, notes)
    if via is None:
        # 备用策略：CIM 定义回写（版本字符串 V2/V3 因 Pro 版本而异，待实机校准）
        for ver in ("V3", "V2"):
            try:
                defn = layer.getDefinition(ver)
                defn.visible = visible
                layer.setDefinition(defn)
                via = "CIM:%s.visible" % ver
                break
            except Exception as e:
                notes.append("CIM %s failed: %s" % (ver, e))
    if via is None:
        raise RuntimeError("NOT_SUPPORTED: 图层显隐无可用设置途径；notes=%s；layer_methods=%s"
                           % (notes, _methods_hint(layer)))
    now, _ = _try_attrs(layer, ["visible"])
    return {"mode": mode, "layer": names[idx], "index": idx,
            "visible_set_to": visible,
            "visible_now": now if isinstance(now, bool) else None, "via": via}


def _extent_dict(ext):
    out = {}
    for key, names in (("xmin", ["XMin"]), ("ymin", ["YMin"]),
                       ("xmax", ["XMax"]), ("ymax", ["YMax"])):
        v, _ = _try_attrs(ext, names)
        out[key] = v if isinstance(v, (int, float)) else None
    sr, _ = _try_attrs(ext, ["spatialReference"])
    sr_name, _ = _try_attrs(sr, ["name"]) if sr is not None else (None, None)
    out["spatial_reference"] = _safe_str(sr_name)
    return out


def tool_zoom_to_layer(args):
    """视图级：把活动视图缩放到图层范围。走 activeView.camera（待实机校准）。"""
    proj, mode = _require_project()
    selector = args.get("layer")
    if selector is None:
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名或下标）")
    map_obj = _find_map(proj, args.get("map"))
    layer, idx, names = _find_layer(map_obj, selector)
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s" % (selector, names))
    notes = []
    # 取范围：策略 1 arcpy.Describe(layer)；策略 2 Describe(dataSource)
    ext = None
    ext_via = None
    try:
        import arcpy
        try:
            desc = arcpy.Describe(layer)
            ext, _ = _try_attrs(desc, ["extent"])
            if ext is not None:
                ext_via = "arcpy.Describe(layer).extent"
        except Exception as e:
            notes.append("Describe(layer) failed: %s" % e)
        if ext is None:
            ds, _ = _try_attrs(layer, ["dataSource"])
            if ds:
                try:
                    desc = arcpy.Describe(ds)
                    ext, _ = _try_attrs(desc, ["extent"])
                    if ext is not None:
                        ext_via = "arcpy.Describe(dataSource).extent"
                except Exception as e:
                    notes.append("Describe(dataSource) failed: %s" % e)
    except Exception as e:
        notes.append("import arcpy failed: %s" % e)
    if ext is None:
        raise RuntimeError("NOT_SUPPORTED: 图层范围不可得；notes=%s；layer_methods=%s"
                           % (notes, _methods_hint(layer)))
    # 设置到活动视图相机
    view, _ = _try_attrs(proj, ["activeView"])
    if view is None:
        raise RuntimeError("NOT_SUPPORTED: 当前无活动视图（activeView 不可用，"
                           "例如桥跑在无界面的 Notebook 会话里）；extent 已取得 %s，"
                           "请在 Pro 里打开该地图的地图视图后重试" % _extent_dict(ext))
    camera, _ = _try_attrs(view, ["camera"])
    if camera is None:
        raise RuntimeError("NOT_SUPPORTED: 活动视图无 camera；view_methods=%s"
                           % _methods_hint(view))
    _res, via = _call_first(camera, ["setExtent"], [(ext,)], notes)
    if via is None:
        via = _set_first(camera, [], ["extent"], ext, notes)
    if via is None:
        raise RuntimeError("NOT_SUPPORTED: 范围已取得但无法写入相机；notes=%s；"
                           "camera_methods=%s" % (notes, _methods_hint(camera)))
    return {"zoomed": True, "mode": mode, "layer": names[idx], "index": idx,
            "extent": _extent_dict(ext), "extent_via": ext_via, "via": via}


def tool_set_labels_visible(args):
    """视图级：开关图层标注。多策略：showLabels 属性 → CIM definition（待实机校准）。"""
    proj, mode = _require_project()
    selector = args.get("layer")
    visible = args.get("visible")
    if selector is None or not isinstance(visible, bool):
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名或下标）与 visible（布尔）")
    map_obj = _find_map(proj, args.get("map"))
    layer, idx, names = _find_layer(map_obj, selector)
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s" % (selector, names))
    notes = []
    via = _set_first(layer, [], ["showLabels"], visible, notes)
    if via is None:
        # 备用策略：CIM 定义。标注开关在 CIM 中的确切位置因图层类型而异，待实机校准。
        for ver in ("V3", "V2"):
            try:
                defn = layer.getDefinition(ver)
                target = getattr(defn, "featureTable", None) or defn
                target.showLabels = visible
                layer.setDefinition(defn)
                via = "CIM:%s.showLabels" % ver
                break
            except Exception as e:
                notes.append("CIM %s failed: %s" % (ver, e))
    if via is None:
        raise RuntimeError("NOT_SUPPORTED: 图层标注开关无可用设置途径；notes=%s；"
                           "layer_methods=%s" % (notes, _methods_hint(layer)))
    now, _ = _try_attrs(layer, ["showLabels"])
    return {"mode": mode, "layer": names[idx], "index": idx,
            "labels_set_to": visible,
            "labels_now": now if isinstance(now, bool) else None, "via": via,
            "note": "labels_now 读回为 null 时以 Pro 界面显示为准"}


# ------------------------------------------------------------ 写工具（confirm 闸）
def tool_add_layer_from_path(args):
    """写类（内容级）：把数据路径加入地图。须 confirm=true。策略：Map.addDataFromPath。"""
    if args.get("confirm") is not True:
        return {"added": False, "reason": "add_layer_from_path 需要 confirm=true 显式确认"}
    proj, mode = _require_project()
    path = args.get("path")
    if not path:
        raise RuntimeError("BAD_ARGS: 必须提供 path（要加入的数据路径）")
    if not os.path.exists(path):
        raise RuntimeError("DATA_NOT_FOUND: 数据路径不存在: %s" % path)
    map_obj = _find_map(proj, args.get("map"))
    before = len(_to_list(_try_attrs(map_obj, ["listLayers"])[0]))
    notes = []
    result, via = _call_first(map_obj, ["addDataFromPath"], [(path,)], notes)
    if via is None:
        raise RuntimeError("ADD_LAYER_FAILED: addDataFromPath 不可用或失败；notes=%s；"
                           "map_methods=%s" % (notes, _methods_hint(map_obj)))
    after_layers = _to_list(_try_attrs(map_obj, ["listLayers"])[0])
    new_name = None
    if result is not None:
        nm, _ = _try_attrs(result, ["name"])
        new_name = _safe_str(nm)
    if new_name is None and after_layers:
        nm, _ = _try_attrs(after_layers[0], ["name"])
        new_name = _safe_str(nm)
    return {"added": True, "mode": mode, "via": via, "path": path,
            "layer_name": new_name,
            "layers_before": before, "layers_after": len(after_layers),
            "note": "layers_after 未变化不等于失败，请用 list_layers 复核并以界面为准"}


def tool_save_project(args):
    """写类：保存当前工程。须 confirm=true。"""
    if args.get("confirm") is not True:
        return {"saved": False, "reason": "save_project 需要 confirm=true 显式确认"}
    proj, mode = _require_project()
    save_fn = getattr(proj, "save", None)
    if not callable(save_fn):
        raise RuntimeError("NOT_SUPPORTED: 工程对象无 save 方法；project_methods=%s"
                           % _methods_hint(proj))
    save_fn()  # 失败时抛错，由 handle_request 结构化回传原始信息，不假装成功
    fp, _ = _try_attrs(proj, ["filePath"])
    return {"saved": True, "mode": mode, "via": "ArcGISProject.save",
            "file_path": _safe_str(fp),
            "note": "mode=file-fallback 时保存的是文件回退打开的那个 .aprx，不是界面里的工程"}


# ------------------------------------------------------------ 只读出文件
def tool_export_map_image(args):
    """只读出文件：导出布局/地图框为 PNG。以文件真落盘且字节>0 为成功标准。
    策略：Layout.exportToPNG → MapFrame.exportToPNG（待实机校准）。"""
    proj, mode = _require_project()
    out_path = args.get("out_path")
    if not out_path:
        raise RuntimeError("BAD_ARGS: 必须提供 out_path（PNG 输出路径）")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(out_dir):
        raise RuntimeError("BAD_ARGS: 输出目录不存在: %s" % out_dir)
    resolution = args.get("resolution")
    if not isinstance(resolution, int) or resolution <= 0:
        resolution = 200
    width, height = args.get("width"), args.get("height")
    notes = []
    layouts = _to_list(_try_attrs(proj, ["listLayouts"])[0])
    layout_names = [_safe_str(_try_attrs(lo, ["name"])[0]) for lo in layouts]
    target = None
    want = args.get("layout")
    for lo in layouts:
        if want is not None and _safe_str(_try_attrs(lo, ["name"])[0]) == want:
            target = lo
            break
    if target is None and want is None and len(layouts) == 1:
        target = layouts[0]

    def _landed(via):
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return {"exported": True, "mode": mode, "via": via, "path": out_path,
                    "bytes": os.path.getsize(out_path)}
        return None

    if target is not None:
        _res, via = _call_first(target, ["exportToPNG"],
                                [(out_path, resolution), (out_path,)], notes)
        if via:
            done = _landed("Layout.%s" % via)
            if done:
                return done
            notes.append("Layout.%s 调用未报错但文件未落盘，不算成功" % via)
    # 地图框策略：遍历全部布局的地图框
    for lo in layouts:
        try:
            frames = lo.listElements("MAPFRAME_ELEMENT")
        except Exception as e:
            notes.append("listElements on %r failed: %s"
                         % (_safe_str(_try_attrs(lo, ["name"])[0]), e))
            continue
        for mf in _to_list(frames):
            variants = [(out_path,)]
            if isinstance(width, int) and isinstance(height, int):
                variants.append((out_path, width, height))
            _res, via = _call_first(mf, ["exportToPNG"], variants, notes)
            if via:
                done = _landed("MapFrame.%s" % via)
                if done:
                    return done
                notes.append("MapFrame.%s 调用未报错但文件未落盘，不算成功" % via)
    if not layouts:
        raise RuntimeError("NOT_SUPPORTED: 工程内没有任何布局（Layout），"
                           "地图视图本身没有可靠的直接导出图片 API；"
                           "请先在 Pro 里新建布局并放入地图框。notes=%s" % notes)
    raise RuntimeError("NOT_SUPPORTED: 全部导出策略失败或未落盘；layouts=%s；notes=%s"
                       % (layout_names, notes))


TOOLS = {
    "ping": tool_ping,
    "discover": tool_discover,
    "project_info": tool_project_info,
    "list_maps": tool_list_maps,
    "list_layers": tool_list_layers,
    "list_tables": tool_list_tables,
    "list_layouts": tool_list_layouts,
    "set_layer_visible": tool_set_layer_visible,
    "zoom_to_layer": tool_zoom_to_layer,
    "set_labels_visible": tool_set_labels_visible,
    "add_layer_from_path": tool_add_layer_from_path,
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
        return {"ok": True, "result": fn(req.get("args") or {})}
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
    print("[arcgis-pro-live-bridge] listening on %s:%d token_file=%s" % (HOST, PORT, TOKEN_FILE))
    print("[arcgis-pro-live-bridge] tools: %s" % ", ".join(sorted(TOOLS)))
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
    if blocking:
        serve()
    else:
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        return t


if __name__ == "__main__":
    start(blocking=True)
else:
    # 在 Pro 的 Python 窗口/Notebook 里被 exec/run 时：起后台线程，不阻塞控制台
    start(blocking=False)
