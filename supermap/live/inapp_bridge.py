# -*- coding: utf-8 -*-
"""
inapp_bridge.py — SuperMap iDesktopX 应用内实时桥（v0.3）

运行位置：iDesktopX 的 Python 窗口内（不是外部命令行）。
作用：在本机 127.0.0.1:47615 开一个行分隔 JSON 的 TCP 服务，
外部的 MCP 服务端（mcp_server.py）把工具调用转发进来，
桥在 iDesktopX 的 Python 会话里执行，操作当前工作空间。

安全：
  - 只监听 127.0.0.1；每次启动生成随机 token，写入 ~/.supermap-live-bridge.token，
    请求必须带对 token，否则拒绝。
  - 内容级写工具（add_dataset_to_map / make_label_thematic / save_workspace）
    需要 args.confirm == true 才执行；视图级操作（set_layer_visible /
    zoom_to_dataset）不设闸，但只改显示状态、可逆，风险等级见 LIVE.md。

实时工作空间的获取方式因 iDesktopX 版本/注入方式而异，本脚本用多策略发现：
  1) Python 窗口注入的全局变量（workspace / current_workspace / ws 等）
  2) 候选桌面模块的 getter（supermap / idesktop / desktop 等模块）
  3) 文件回退：环境变量 SM_LIVE_WORKSPACE_PATH 指向的工作空间文件（经 iobjectspy 打开；
     是否与 GUI 同一对象取决于版本，结果里会标注 mode=file-fallback，不能假装是实时对象）
discover 工具会把发现过程与现场对象的方法清单一并回报，供维护者据实收紧策略。

v0.3 新增操作类工具（add_dataset_to_map / set_layer_visible / zoom_to_dataset /
make_label_thematic / export_map_image / list_layers）全部为实验性实现：
地图对象、图层集合、专题图与导出 API 在不同 iDesktopX/iobjectspy 版本上命名差异大，
一律多策略尝试并回报命中的策略（via 字段）；拿不到对象或 API 不匹配时返回
结构化错误（NOT_SUPPORTED / *_FAILED，附现场方法清单线索），绝不假装成功。
上述工具的 iDesktopX 实时路径仍未在真实 iDesktopX 上验证，首次实机使用须按
校准指南的顺序逐项校准；文件回退路径已在 iDesktop 10i 上完成实机校准，
见 docs/CALIBRATION-RESULTS-20261024.md。

单文件约束：本文件必须能被 iDesktopX Python 窗口单文件 exec 运行，无法 import
同包模块，因此数据源/数据集枚举的共享逻辑（ENUM-SHARED 块）以内联副本形式维护，
与 scripts/supermap_bridge.py 的同名块保持一致，改一侧必须同步另一侧。
"""
import json
import os
import socket
import sys
import tempfile
import threading
import traceback
import uuid


def _ensure_writable_cwd():
    """iobjectspy 会往当前工作目录写 iobjectspy.log；CWD 只读时（如被宿主程序以子进程拉起、当前目录又在
    iDesktopX 安装目录）会 PermissionError 导致工作空间打不开。这里检测并切到临时目录。
    """
    try:
        probe = os.path.join(os.getcwd(), ".sm_bridge_cwd_probe")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return
    except Exception:
        pass
    try:
        os.chdir(tempfile.mkdtemp(prefix="sm-bridge-"))
    except Exception:
        pass


_ensure_writable_cwd()

HOST = "127.0.0.1"
PORT = 47615
# token 文件位置可用 SM_BRIDGE_TOKEN_FILE 覆盖（受限环境里 ~ 可能不可写）；MCP 侧同名变量
TOKEN_FILE = os.environ.get("SM_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".supermap-live-bridge.token")
# 沙箱/受限环境里子进程可能写不了 ~，允许用环境变量直接指定 token（MCP 侧同名变量优先读取）
TOKEN = os.environ.get("SM_BRIDGE_TOKEN") or uuid.uuid4().hex

_state = {"workspace": None, "mode": None, "attempts": []}


# ==== ENUM-SHARED-BEGIN =====================================================
# 数据源/数据集枚举的共享实现，与本包另一侧桥（无头桥 scripts/supermap_bridge.py
# / 实时桥 live/inapp_bridge.py）中的同名块保持逐字一致：两侧运行形态不同
# （一个是命令行脚本、一个必须单文件在 iDesktopX Python 窗口 exec），无法互相
# import，只能以内联副本同步维护。修改任一侧后必须同步另一侧。
def _try_attrs(obj, names):
    """按顺序尝试属性/方法，返回 (值, 命中的名字)；方法会自动调用（无参）。"""
    for name in names:
        if obj is None or not hasattr(obj, name):
            continue
        val = getattr(obj, name)
        try:
            if callable(val):
                val = val()
            return val, name
        except Exception:
            continue
    return None, None


def _get_item(coll, i):
    """集合下标访问兜底：coll[i] / coll.get(i) / coll.get_item(i) / coll.item(i)。"""
    try:
        return coll[i]
    except Exception:
        pass
    for name in ("get", "get_item", "item"):
        fn = getattr(coll, name, None)
        if callable(fn):
            try:
                return fn(i)
            except Exception:
                continue
    return None


def _to_list(coll):
    """把集合尽量转成 list：可迭代优先，其次 count+下标兜底。"""
    if coll is None:
        return []
    try:
        return list(coll)
    except Exception:
        pass
    count, _ = _try_attrs(coll, ["get_count", "count"])
    if not isinstance(count, int):
        try:
            count = len(coll)
        except Exception:
            count = None
    if isinstance(count, int):
        return [_get_item(coll, i) for i in range(count)]
    return []


def _safe_str(v):
    try:
        return str(v)
    except Exception:
        return None


def _ds_summary(ds):
    alias, _ = _try_attrs(ds, ["get_alias", "alias", "get_name", "name"])
    engine, _ = _try_attrs(ds, ["get_engine_type", "engine_type"])
    if engine is None:
        # iobjectspy 10.1.0 实机验证：引擎类型挂在 connection_info.type 上
        conn, _ = _try_attrs(ds, ["get_connection_info", "connection_info"])
        if conn is not None:
            engine, _ = _try_attrs(conn, ["get_type", "type"])
    return {"alias": _safe_str(alias),
            "engine": _safe_str(getattr(engine, "name", engine))}


def _dataset_entry(d):
    name, _ = _try_attrs(d, ["get_name", "name"])
    dtype, _ = _try_attrs(d, ["get_type", "type"])
    return {"name": _safe_str(name), "type": _safe_str(dtype)}
# ==== ENUM-SHARED-END =======================================================


def discover_workspace(force=False):
    """多策略发现当前工作空间；返回 (workspace, mode, attempts)。"""
    if _state["workspace"] is not None and not force:
        return _state["workspace"], _state["mode"], _state["attempts"]
    attempts = []
    candidates = []
    # 策略 1：注入的全局变量（本模块 globals 与 __main__ globals 都查）
    import __main__
    for scope_name, scope in (("bridge_globals", globals()), ("__main__", vars(__main__))):
        for key in ("workspace", "current_workspace", "currentWorkspace", "ws"):
            obj = scope.get(key)
            if obj is not None:
                candidates.append(("%s.%s" % (scope_name, key), obj))
    # 策略 2：候选桌面模块的 getter / 属性
    for mod_name in ("supermap", "idesktop", "desktop", "iobjectspy.desktop"):
        try:
            mod = __import__(mod_name)
        except Exception:
            continue
        for attr in ("get_workspace", "current_workspace", "get_current_workspace", "workspace"):
            if hasattr(mod, attr):
                val = getattr(mod, attr)
                try:
                    if callable(val):
                        val = val()
                    if val is not None:
                        candidates.append(("%s.%s" % (mod_name, attr), val))
                except Exception as e:
                    attempts.append("%s.%s failed: %s" % (mod_name, attr, e))
    for label, obj in candidates:
        # 校验：能枚举数据源才认作工作空间
        coll, via = _try_attrs(obj, ["get_datasources", "datasources"])
        if coll is not None or via is not None:
            attempts.append("accepted %s (datasources via %s)" % (label, via))
            _state.update(workspace=obj, mode="live:" + label, attempts=attempts)
            return obj, _state["mode"], attempts
        attempts.append("rejected %s (no datasources accessor)" % label)
    # 策略 3：文件回退
    path = os.environ.get("SM_LIVE_WORKSPACE_PATH")
    if path and os.path.isfile(path):
        try:
            from iobjectspy import Workspace, WorkspaceConnectionInfo
            ws = Workspace()
            # iobjectspy 10.1.0 实测：open() 接收 WorkspaceConnectionInfo，且返回新对象
            opened = ws.open(WorkspaceConnectionInfo(path))
            if opened is not None:
                ws = opened
            attempts.append("file-fallback opened %s" % path)
            _state.update(workspace=ws, mode="file-fallback", attempts=attempts)
            return ws, "file-fallback", attempts
        except Exception as e:
            attempts.append("file-fallback failed: %s" % e)
    _state.update(workspace=None, mode=None, attempts=attempts)
    return None, None, attempts


def _require_workspace():
    ws, mode, attempts = discover_workspace()
    if ws is None:
        raise RuntimeError("LIVE_WORKSPACE_NOT_FOUND: 未发现当前工作空间；attempts=%s" % attempts)
    return ws, mode


# ------------------------------------------------------------ 通用调用助手
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


# ------------------------------------------------------------ 数据集定位
def _find_datasource(ws, alias):
    coll, _ = _try_attrs(ws, ["get_datasources", "datasources"])
    available = []
    for ds in _to_list(coll):
        if ds is None:
            continue
        summary = _ds_summary(ds)
        available.append(summary["alias"])
        if alias is None or summary["alias"] == alias:
            return ds, available
    return None, available


def _find_dataset(ws, ds_alias, ds_name):
    """返回 (dataset_obj, datasource_alias, 可用数据集名列表)。"""
    ds, _aliases = _find_datasource(ws, ds_alias)
    if ds is None:
        raise RuntimeError("DATASOURCE_NOT_FOUND: 数据源 %r 不存在" % ds_alias)
    dcoll, _ = _try_attrs(ds, ["get_datasets", "datasets"])
    available = []
    for d in _to_list(dcoll):
        if d is None:
            continue
        entry = _dataset_entry(d)
        available.append(entry["name"])
        if entry["name"] == ds_name:
            return d, _ds_summary(ds)["alias"], available
    raise RuntimeError("DATASET_NOT_FOUND: 数据集 %r 不在数据源 %r 中；可用: %s"
                       % (ds_name, ds_alias, available))


# ------------------------------------------------------------ 地图/图层定位
def _open_map_object(ws, target, notes):
    """构造 iobjectspy.mapping.Map 并绑定工作空间、按名打开；多策略。"""
    try:
        from iobjectspy.mapping import Map as MapCls
    except Exception as e:
        notes.append("import iobjectspy.mapping.Map failed: %s" % e)
        return None, None
    candidates = []
    try:
        candidates.append(("Map(ws)", MapCls(ws)))
    except Exception as e:
        notes.append("Map(ws) failed: %s" % e)
    try:
        m = MapCls()
        attached = False
        for setter in ("set_workspace", "setWorkspace"):
            fn = getattr(m, setter, None)
            if callable(fn):
                try:
                    fn(ws)
                    attached = True
                    break
                except Exception as e:
                    notes.append("%s failed: %s" % (setter, e))
        if not attached:
            try:
                m.workspace = ws
                attached = True
            except Exception as e:
                notes.append("Map.workspace assign failed: %s" % e)
        candidates.append(("Map()+attach(workspace=%s)" % attached, m))
    except Exception as e:
        notes.append("Map() failed: %s" % e)
    for label, m in candidates:
        if target is None:
            return m, label
        _res, via = _call_first(m, ["open", "load", "open_map", "openMap"],
                                [(target,)], notes)
        if via:
            return m, "%s + %s" % (label, via)
        if hasattr(m, "get_layers") or hasattr(m, "layers"):
            return m, label + " (未按名打开，假定为当前地图，须人工核对)"
    return None, None


def _get_map(ws, map_name):
    """返回 (map_obj, via, notes)。maps 集合元素若本身带 layers 访问器直接用，
    否则按名构造 Map 打开。拿不到就抛 MAP_ACCESS_FAILED（附全部尝试记录）。"""
    notes = []
    maps_coll, _ = _try_attrs(ws, ["get_maps", "maps"])
    items = [m for m in _to_list(maps_coll) if m is not None]
    target = map_name
    for m in items:
        nm, _ = _try_attrs(m, ["get_name", "name"])
        label = _safe_str(nm if nm is not None else m)
        if map_name is not None and label != map_name:
            continue
        if hasattr(m, "get_layers") or hasattr(m, "layers"):
            return m, "workspace.maps[%s]" % label, notes
        if target is None:
            target = label
        break
    mobj, via = _open_map_object(ws, target, notes)
    if mobj is None:
        raise RuntimeError("MAP_ACCESS_FAILED: 地图 %r 无法打开；notes=%s" % (target, notes))
    return mobj, via, notes


def _commit_map(ws, map_obj, notes):
    """把改动后的地图写回工作空间（iobjectspy 10.1 实机结论）。

    get_map/get_maps 每次都返回新的 Map 包装对象；只在包装对象上改图层/专题，
    后续请求（以及 save()）都看不到。必须 ws.set_map(名字, map_obj) 回写，
    再 save 才会落盘。返回是否回写成功。
    """
    name, _ = _try_attrs(map_obj, ["get_name", "name"])
    if name is None:
        notes.append("commit skipped: map 对象没有名字")
        return False
    res, via = _call_first(ws, ["set_map"], [(name, map_obj)], notes)
    if res:
        notes.append("已通过 %s 回写地图 %r" % (via, name))
        return True
    notes.append("地图回写失败（set_map 返回 %r）" % (res,))
    return False


def _layers_of(map_obj):
    layers, _via = _try_attrs(map_obj, ["get_layers", "layers"])
    if layers is None:
        raise RuntimeError("NOT_SUPPORTED: 地图对象无 layers 访问器；map_methods=%s"
                           % _methods_hint(map_obj))
    return layers


def _layer_name(ly):
    nm, _ = _try_attrs(ly, ["get_name", "name", "get_caption", "caption"])
    return _safe_str(nm)


def _layer_visible(ly):
    v, _ = _try_attrs(ly, ["get_is_visible", "is_visible", "get_visible", "visible"])
    return v if isinstance(v, bool) else None


def _find_layer(layers, selector):
    """selector 可为图层名、整数下标或数字字符串下标。返回 (layer, index, 全部图层名)。"""
    if isinstance(selector, str) and selector.isdigit():
        selector = int(selector)
    items = _to_list(layers)
    names = []
    found = (None, None)
    for i, ly in enumerate(items):
        if ly is None:
            names.append(None)
            continue
        nm = _layer_name(ly)
        names.append(nm)
        if isinstance(selector, int) and selector == i:
            found = (ly, i)
        elif isinstance(selector, str) and nm == selector:
            found = (ly, i)
    return found[0], found[1], names


# ------------------------------------------------------------ 只读工具
def tool_ping(args):
    return {"pong": True, "bridge": "supermap-live-bridge/0.3", "python": sys.version.split()[0]}


def tool_discover(args):
    ws, mode, attempts = discover_workspace(force=True)
    report = {"mode": mode, "attempts": attempts, "workspace_found": ws is not None}
    if ws is not None:
        report["workspace_type"] = str(type(ws))
        report["workspace_methods"] = _methods_hint(ws, 200)
    try:
        import iobjectspy
        report["iobjectspy_version"] = getattr(iobjectspy, "__version__", "unknown")
        report["iobjectspy_file"] = getattr(iobjectspy, "__file__", "unknown")
    except Exception as e:
        report["iobjectspy_error"] = str(e)
    try:
        from iobjectspy.mapping import Map as _MapCls
        report["map_class_methods"] = _methods_hint(_MapCls, 200)
    except Exception as e:
        report["map_class_error"] = str(e)
    import __main__
    report["main_globals"] = [k for k in vars(__main__).keys() if not k.startswith("_")][:100]
    return report


def tool_workspace_info(args):
    ws, mode = _require_workspace()
    coll, _ = _try_attrs(ws, ["get_datasources", "datasources"])
    maps, _ = _try_attrs(ws, ["get_maps", "maps"])
    return {"mode": mode,
            "datasource_count": len(_to_list(coll)),
            "map_count": len(_to_list(maps))}


def tool_list_datasources(args):
    ws, mode = _require_workspace()
    coll, _ = _try_attrs(ws, ["get_datasources", "datasources"])
    return {"mode": mode, "datasources": [_ds_summary(ds) for ds in _to_list(coll) if ds is not None]}


def tool_list_datasets(args):
    ws, mode = _require_workspace()
    alias = args.get("datasource")
    coll, _ = _try_attrs(ws, ["get_datasources", "datasources"])
    out = []
    for ds in _to_list(coll):
        if ds is None:
            continue
        summary = _ds_summary(ds)
        if alias and summary["alias"] != alias:
            continue
        dcoll, _ = _try_attrs(ds, ["get_datasets", "datasets"])
        names = [_dataset_entry(d) for d in _to_list(dcoll) if d is not None]
        out.append({"datasource": summary["alias"], "datasets": names})
    return {"mode": mode, "result": out}


def tool_list_maps(args):
    ws, mode = _require_workspace()
    maps, _ = _try_attrs(ws, ["get_maps", "maps"])
    names = []
    for m in _to_list(maps):
        nm, _ = _try_attrs(m, ["get_name", "name"])
        names.append(_safe_str(nm if nm is not None else m))
    return {"mode": mode, "maps": names}


def tool_list_layers(args):
    ws, mode = _require_workspace()
    map_obj, map_via, _notes = _get_map(ws, args.get("map"))
    layers = _layers_of(map_obj)
    out = []
    for i, ly in enumerate(_to_list(layers)):
        if ly is None:
            continue
        out.append({"index": i, "name": _layer_name(ly), "visible": _layer_visible(ly)})
    return {"mode": mode, "map_via": map_via, "layers": out}


# ------------------------------------------------------------ 操作工具（实验性）
def tool_add_dataset_to_map(args):
    """写类（内容级）：把数据集加入地图。须 confirm=true。"""
    if args.get("confirm") is not True:
        return {"added": False, "reason": "add_dataset_to_map 需要 confirm=true 显式确认"}
    ws, mode = _require_workspace()
    ds_name = args.get("dataset")
    if not ds_name:
        raise RuntimeError("BAD_ARGS: 必须提供 dataset（数据集名）")
    dataset_obj, ds_alias, _avail = _find_dataset(ws, args.get("datasource"), ds_name)
    map_obj, map_via, notes = _get_map(ws, args.get("map"))
    layers = _layers_of(map_obj)
    before = len(_to_list(layers))
    # 策略组 1：Layers.add(dataset[, toHead]) —— iObjects 的标准签名
    result, via = _call_first(layers, ["add", "add_dataset", "insert"],
                              [(dataset_obj,), (dataset_obj, True)], notes)
    # 策略组 2：Map 级 add_dataset
    if via is None:
        result, via = _call_first(map_obj, ["add_dataset", "addDataset"],
                                  [(dataset_obj,)], notes)
    if via is None:
        raise RuntimeError("ADD_DATASET_FAILED: 全部添加策略失败；map_via=%s；notes=%s；"
                           "layers_methods=%s" % (map_via, notes, _methods_hint(layers)))
    # 刷新图层清单：iobjectspy 10.1 的 get_layers() 返回 list 快照，必须重新取一次
    fresh_layers, _ = _try_attrs(map_obj, ["get_layers", "layers"])
    after_items = _to_list(fresh_layers if fresh_layers is not None else layers)
    committed = _commit_map(ws, map_obj, notes)
    return {"added": True, "mode": mode, "map_via": map_via, "via": via,
            "datasource": ds_alias, "dataset": ds_name,
            "returned": _safe_str(result), "committed": committed,
            "layers_before": before, "layers_after": len(after_items),
            "note": "committed=false 表示改动只在本次请求的 Map 包装对象上；"
                    "committed=true 表示已 set_map 回写工作空间，后续 list_layers 应能看到"}


def tool_set_layer_visible(args):
    """视图级：设置图层显隐（只改显示状态、可逆，无 confirm 闸；见 LIVE.md 风险等级）。"""
    ws, mode = _require_workspace()
    selector = args.get("layer")
    visible = args.get("visible")
    if selector is None or not isinstance(visible, bool):
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名或下标）与 visible（布尔）")
    map_obj, map_via, _n = _get_map(ws, args.get("map"))
    layers = _layers_of(map_obj)
    layer, idx, names = _find_layer(layers, selector)
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s" % (selector, names))
    notes = []
    via = _set_first(layer,
                     ["set_visible", "set_is_visible", "setVisible", "set_display"],
                     ["visible", "is_visible"], visible, notes)
    if via is None:
        raise RuntimeError("NOT_SUPPORTED: 图层对象无显隐设置途径；notes=%s；layer_methods=%s"
                           % (notes, _methods_hint(layer)))
    committed = _commit_map(ws, map_obj, notes)
    return {"mode": mode, "map_via": map_via, "layer": names[idx], "index": idx,
            "visible_set_to": visible, "visible_now": _layer_visible(layer),
            "via": via, "committed": committed}


def _dataset_bounds(dataset_obj):
    rect, _via = _try_attrs(dataset_obj, ["get_bounds", "bounds"])
    if rect is None:
        return None
    vals = {}
    for key, names in (("left", ["get_left", "left"]),
                       ("bottom", ["get_bottom", "bottom"]),
                       ("right", ["get_right", "right"]),
                       ("top", ["get_top", "top"])):
        v, _ = _try_attrs(rect, names)
        vals[key] = v if isinstance(v, (int, float)) else None
    vals["raw"] = _safe_str(rect)
    return vals


def _make_rect(left, bottom, right, top, notes):
    for mod_name, cls_name in (("iobjectspy.data", "Rectangle2D"),
                               ("iobjectspy.mapping", "Rectangle2D")):
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
        except Exception:
            continue
        try:
            return cls(left, bottom, right, top)
        except Exception as e:
            notes.append("%s.%s(4args) failed: %s" % (mod_name, cls_name, e))
        try:
            rc = cls()
            ok = True
            for setter, val in (("set_left", left), ("set_bottom", bottom),
                                ("set_right", right), ("set_top", top)):
                fn = getattr(rc, setter, None)
                if callable(fn):
                    fn(val)
                else:
                    setattr(rc, setter.replace("set_", ""), val)
            if ok:
                return rc
        except Exception as e:
            notes.append("%s.%s setters failed: %s" % (mod_name, cls_name, e))
    return None


def tool_zoom_to_dataset(args):
    """视图级：把地图视图缩放到数据集范围。拿不到范围或设不进视图 → NOT_SUPPORTED。"""
    ws, mode = _require_workspace()
    ds_name = args.get("dataset")
    if not ds_name:
        raise RuntimeError("BAD_ARGS: 必须提供 dataset（数据集名）")
    dataset_obj, _alias, _avail = _find_dataset(ws, args.get("datasource"), ds_name)
    bounds = _dataset_bounds(dataset_obj)
    if bounds is None or any(bounds[k] is None for k in ("left", "bottom", "right", "top")):
        raise RuntimeError("NOT_SUPPORTED: 数据集范围不可得（bounds=%s）；"
                           "dataset_methods=%s" % (bounds, _methods_hint(dataset_obj)))
    map_obj, map_via, notes = _get_map(ws, args.get("map"))
    via = None
    # 策略 0（iobjectspy 10.1 实测）：dataset.bounds 本身就是 Rectangle，可直接传给 set_view_bounds
    raw_rect, _ = _try_attrs(dataset_obj, ["get_bounds", "bounds"])
    if raw_rect is not None:
        _r, via = _call_first(map_obj, ["set_view_bounds", "set_view_extent"],
                              [(raw_rect,)], notes)
    rect = _make_rect(bounds["left"], bounds["bottom"], bounds["right"], bounds["top"], notes)
    if via is None and rect is not None:
        _res, via = _call_first(map_obj,
                                ["set_view_bounds", "set_view_extent", "zoom_to_bounds",
                                 "set_bounds", "setViewBounds"],
                                [(rect,)], notes)
        if via is None:
            via = _set_first(map_obj, [], ["view_bounds", "view_extent"], rect, notes)
    if via is None:
        _res, via = _call_first(map_obj, ["zoom_to_bounds", "set_view_bounds"],
                                [(bounds["left"], bounds["bottom"],
                                  bounds["right"], bounds["top"])], notes)
    if via is None:
        raise RuntimeError("NOT_SUPPORTED: 数据集范围已取得 %s，但无法设置到地图视图；"
                           "map_via=%s；notes=%s；map_methods=%s"
                           % (bounds, map_via, notes, _methods_hint(map_obj)))
    # 刷新是尽力而为：失败不推翻缩放结果，但要如实记录
    refresh_via = None
    _r, refresh_via = _call_first(map_obj, ["refresh", "Refresh"], [()], notes)
    return {"zoomed": True, "mode": mode, "map_via": map_via, "via": via,
            "bounds": {k: bounds[k] for k in ("left", "bottom", "right", "top")},
            "refresh_via": refresh_via}


def tool_make_label_thematic(args):
    """写类（内容级）：按字段给图层/数据集做标签专题图。须 confirm=true。"""
    if args.get("confirm") is not True:
        return {"thematic_created": False,
                "reason": "make_label_thematic 需要 confirm=true 显式确认"}
    ws, mode = _require_workspace()
    field = args.get("field")
    if not field:
        raise RuntimeError("BAD_ARGS: 必须提供 field（标签字段名，如 NAME）")
    map_obj, map_via, notes = _get_map(ws, args.get("map"))
    layers = _layers_of(map_obj)
    # 目标：优先已有图层（layer 参数或与 dataset 同名图层），否则用数据集新建专题图层
    layer, layer_idx, layer_names = (None, None, [])
    selector = args.get("layer") or args.get("dataset")
    if selector is not None:
        layer, layer_idx, layer_names = _find_layer(layers, selector)
    dataset_obj = None
    if args.get("dataset"):
        dataset_obj, _a, _av = _find_dataset(ws, args.get("datasource"), args["dataset"])
    # 构造 ThemeLabel（类名/签名各版本不一，多策略）
    theme = None
    theme_via = None
    for mod_name, cls_name in (("iobjectspy.mapping", "ThemeLabel"),
                               ("iobjectspy.mapping", "ThemeLabelDefault")):
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            theme = cls()
            theme_via = "%s.%s()" % (mod_name, cls_name)
            break
        except Exception as e:
            notes.append("theme ctor %s.%s failed: %s" % (mod_name, cls_name, e))
    if theme is None:
        raise RuntimeError("NOT_SUPPORTED: ThemeLabel 类不可用；notes=%s" % notes)
    _r, expr_via = _call_first(theme, ["set_label_expression", "set_expression",
                                       "set_field", "setLabelExpression"],
                               [(field,)], notes)
    if expr_via is None:
        expr_via = _set_first(theme, [], ["label_expression", "field", "expression"],
                              field, notes)
    if expr_via is None:
        raise RuntimeError("NOT_SUPPORTED: ThemeLabel 无法设置标签字段 %r；notes=%s；"
                           "theme_methods=%s" % (field, notes, _methods_hint(theme)))
    # 应用（iobjectspy 10.1 实机结论）：
    #   - 已有图层没有可持久化的公开 set_theme；直接用 layer._set_theme 只改 Python 包装对象，
    #     既不进渲染也不进 XML（两张导出图 sha256 相同，可复现）
    #   - 这版唯一可靠的专题入口是 Map.add_dataset(dataset, layer_setting=Theme)，再用
    #     ws.set_map 回写工作空间；重开副本后 get_theme() 仍是 ThemeLabel
    applied_via = None
    committed = False
    theme_now = None
    if dataset_obj is None and layer is not None:
        ds_of_layer, _ = _try_attrs(layer, ["get_dataset", "dataset"])
        if ds_of_layer is not None:
            dataset_obj = ds_of_layer
            notes.append("从已有图层反查到数据集 %r" % _safe_str(getattr(ds_of_layer, "name", ds_of_layer)))
    if dataset_obj is not None:
        try:
            new_layer = map_obj.add_dataset(dataset_obj, layer_setting=theme)
            applied_via = "map.add_dataset(layer_setting=ThemeLabel)"
            theme_now = type(new_layer.get_theme()).__name__ if new_layer is not None else None
            committed = _commit_map(ws, map_obj, notes)
        except Exception as e:
            notes.append("add_dataset(layer_setting=theme) failed: %s" % e)
    if applied_via is None and layer is not None:
        _r, applied_via = _call_first(layer, ["set_theme", "setTheme", "_set_theme"],
                                      [(theme,)], notes)
        if applied_via is not None:
            applied_via += " (仅包装对象，未验证持久化)"
    if applied_via is None:
        raise RuntimeError("THEMATIC_APPLY_FAILED: 专题图已构造（%s, 字段经 %s）但无法应用；"
                           "notes=%s；layers_methods=%s"
                           % (theme_via, expr_via, notes, _methods_hint(layers)))
    return {"thematic_created": True, "mode": mode, "map_via": map_via,
            "theme_via": theme_via, "expression_via": expr_via, "applied_via": applied_via,
            "theme_now": theme_now, "committed": committed, "field": field,
            "layer": layer_names[layer_idx] if layer_idx is not None else None,
            "note": "专题图以新图层形式加入地图（数据图层仍在）；committed=true 表示已回写工作空间，"
                    "save 后重开副本可看到 ThemeLabel"}


def tool_export_map_image(args):
    """只读出文件：把地图导出为 PNG 到指定路径。多策略尝试，以文件真实落盘为准。"""
    ws, mode = _require_workspace()
    out_path = args.get("out_path")
    if not out_path:
        raise RuntimeError("BAD_ARGS: 必须提供 out_path（PNG 输出路径）")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(out_dir):
        raise RuntimeError("BAD_ARGS: 输出目录不存在: %s" % out_dir)
    map_obj, map_via, notes = _get_map(ws, args.get("map"))
    width, height = args.get("width"), args.get("height")
    # 策略 0（iobjectspy 10.1 实测）：output_to_file(file_name, output_bounds=None, dpi=0,
    # image_size=None, ...)。尺寸必须用关键字 image_size=(w, h)；位置传元组会被当成 output_bounds。
    exporter = getattr(map_obj, "output_to_file", None)
    if callable(exporter):
        try:
            if isinstance(width, int) and isinstance(height, int):
                exporter(out_path, image_size=(width, height))
                used = "output_to_file(image_size=(w,h))"
            else:
                exporter(out_path)
                used = "output_to_file()"
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return {"exported": True, "mode": mode, "map_via": map_via,
                        "via": used, "path": out_path,
                        "bytes": os.path.getsize(out_path)}
            notes.append("%s 调用未报错但文件未落盘，不算成功" % used)
        except Exception as e:
            notes.append("output_to_file 关键字策略失败: %s" % e)
    arg_variants = [(out_path,), (out_path, "PNG")]
    if isinstance(width, int) and isinstance(height, int):
        # iobjectspy 10.1 实测签名 output_to_file(file_name, image_size=None, ...)：
        # 尺寸是 (width, height) 元组，而非两个位置参数
        arg_variants.append((out_path, (width, height)))
        arg_variants.append((out_path, width, height))
    method_names = ["output_to_file", "output_to_image", "export_to_image",
                    "output_map_to_image", "save_to_file", "to_image", "output"]
    for name in method_names:
        fn = getattr(map_obj, name, None)
        if not callable(fn):
            continue
        for av in arg_variants:
            try:
                fn(*av)
            except Exception as e:
                notes.append("%s(args=%d) failed: %s" % (name, len(av), e))
                continue
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return {"exported": True, "mode": mode, "map_via": map_via,
                        "via": "%s/%d" % (name, len(av)), "path": out_path,
                        "bytes": os.path.getsize(out_path)}
            notes.append("%s(args=%d) 调用未报错但文件未落盘，不算成功"
                         % (name, len(av)))
    raise RuntimeError("NOT_SUPPORTED: 全部导出策略失败或未落盘；map_via=%s；notes=%s；"
                       "map_methods=%s" % (map_via, notes, _methods_hint(map_obj)))


def tool_save_workspace(args):
    if args.get("confirm") is not True:
        return {"saved": False, "reason": "save_workspace 需要 confirm=true 显式确认"}
    ws, mode = _require_workspace()
    fn, via = _try_attrs(ws, ["save"])
    return {"saved": True, "mode": mode, "via": via}


TOOLS = {
    "ping": tool_ping,
    "discover": tool_discover,
    "workspace_info": tool_workspace_info,
    "list_datasources": tool_list_datasources,
    "list_datasets": tool_list_datasets,
    "list_maps": tool_list_maps,
    "list_layers": tool_list_layers,
    "add_dataset_to_map": tool_add_dataset_to_map,
    "set_layer_visible": tool_set_layer_visible,
    "zoom_to_dataset": tool_zoom_to_dataset,
    "make_label_thematic": tool_make_label_thematic,
    "export_map_image": tool_export_map_image,
    "save_workspace": tool_save_workspace,
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
    if not os.environ.get("SM_BRIDGE_TOKEN"):
        try:
            token_dir = os.path.dirname(TOKEN_FILE)
            if token_dir and not os.path.isdir(token_dir):
                os.makedirs(token_dir)
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(TOKEN)
        except Exception as e:
            print("[supermap-live-bridge] token file write failed: %s" % e)
            print("[supermap-live-bridge] 可改用环境变量 SM_BRIDGE_TOKEN 指定 token")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    print("[supermap-live-bridge] listening on %s:%d token_file=%s" % (HOST, PORT, TOKEN_FILE))
    print("[supermap-live-bridge] tools: %s" % ", ".join(sorted(TOOLS)))
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
    # 在 Python 窗口里被 exec/run 时：起后台线程，不阻塞控制台
    start(blocking=False)
