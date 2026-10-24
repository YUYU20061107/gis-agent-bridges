# -*- coding: utf-8 -*-
"""
inapp_bridge.py — ArcMap 应用内实时桥（v0.2，个人自用）

运行位置：ArcMap 的 Python 窗口内（不是外部命令行）。
作用：在本机 127.0.0.1:47617 开一个行分隔 JSON 的 TCP 服务，外部的 MCP
服务端（mcp_server.py，Python 3）把工具调用转发进来，桥在 ArcMap 的
Python 会话里用 arcpy.mapping 操作当前打开的地图文档（.mxd），
结果实时反映在 ArcMap 界面里。

运行环境现实：ArcMap Desktop 10.x 自带的是 **Python 2.7**，本文件与
scripts/ 下的脚本都写在 Python 2.7 / 3.x 兼容子集上（无 f-string、
无 walrus、无 pathlib；print 走 __future__）。MCP 服务端跑在进程外，
用任意 Python 3，与 ArcMap 的运行时无关。

安全：
  - 只监听 127.0.0.1；每次启动生成随机 token，写入
    ~/.arcmap-live-bridge.token（可用环境变量 ARCMAP_BRIDGE_TOKEN_FILE
    覆盖位置，MCP 侧同名变量须一致），请求必须带对 token，否则拒绝。
  - 唯一的写工具 save_document 需要 args.confirm == true 才执行；
    视图级操作（set_layer_visible / zoom_to_layer）只改显示状态、可逆。

当前文档的多策略发现（结果里标注 mode，file-fallback 不许冒充实时）：
  1) arcpy.mapping.MapDocument("CURRENT") —— ArcMap Python 窗口内的
     官方实时入口，拿到的是 GUI 里正打开的那个文档对象；
  2) 注入的全局变量（mxd / current_mxd / map_document / doc 等，
     本模块 globals 与 __main__ globals 都查，校验有 filePath 属性）；
  3) 文件回退：环境变量 ARCMAP_LIVE_MXD_PATH 指向的 .mxd 文件，
     以文件路径打开——只能看到已保存状态，mode 标注 file-fallback。
discover 工具会把发现过程与现场对象的方法清单一并回报，供校准收紧。

已知实机注意：工具在桥的后台线程里执行 arcpy 调用。ArcMap 的 arcpy
对象带 COM 背景，从非主线程调用在个别版本/场景下可能出现异常或挂起；
若实机出现此类现象，属于校准发现，应如实回报，不要粉饰成成功。

单文件约束：本文件必须能被 ArcMap Python 窗口单文件 execfile/exec 运行，
无法 import 同包模块，所需逻辑全部内联。
"""
from __future__ import print_function

import json
import os
import socket
import sys
import threading
import traceback
import uuid

HOST = "127.0.0.1"
PORT = 47617
# token 文件位置可用 ARCMAP_BRIDGE_TOKEN_FILE 覆盖（MCP 侧同名变量须一致）
TOKEN_FILE = os.environ.get("ARCMAP_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".arcmap-live-bridge.token")
TOKEN = uuid.uuid4().hex

_state = {"mxd": None, "mode": None, "attempts": []}

try:
    _text = unicode  # noqa: F821  Python 2.7
except NameError:
    _text = str


try:
    _TEXT = unicode  # noqa: F821  Python 2.7
except NameError:
    _TEXT = str


def _dec(b):
    """bytes→unicode：UTF-8 → 文件系统编码 → mbcs/gbk → latin-1 逐级尝试。"""
    if isinstance(b, _TEXT):
        return b
    for enc in ("utf-8", None, "mbcs", "gbk", "latin-1"):
        try:
            if enc is None:
                enc = sys.getfilesystemencoding()
                if not enc:
                    continue
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("latin-1", "replace")


def _to_text(obj):
    """递归把 bytes 解成 unicode，保证 py2 下 json.dumps 不会因混类型崩。"""
    if isinstance(obj, dict):
        return dict((_to_text(k), _to_text(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [_to_text(v) for v in obj]
    if isinstance(obj, _TEXT):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        return _dec(obj)
    return obj

def _safe_str(v):
    if v is None:
        return None
    try:
        if isinstance(v, _text):
            return v
        if isinstance(v, bytes):
            return v.decode("utf-8", "replace")
        return _text(v)
    except Exception:
        try:
            return str(v)
        except Exception:
            return None


def _log(msg):
    try:
        sys.stdout.write("%s\n" % msg)
        sys.stdout.flush()
    except Exception:
        pass


def _methods_hint(obj, limit=120):
    try:
        return [n for n in dir(obj) if not n.startswith("_")][:limit]
    except Exception:
        return []


def _import_arcpy():
    import arcpy
    return arcpy


# ------------------------------------------------------------ 文档发现
def _looks_like_mxd(obj):
    return obj is not None and hasattr(obj, "filePath") \
        and hasattr(obj, "save")


def discover_document(force=False):
    """多策略发现当前地图文档；返回 (mxd, mode, attempts)。"""
    if _state["mxd"] is not None and not force:
        return _state["mxd"], _state["mode"], _state["attempts"]
    attempts = []
    try:
        arcpy = _import_arcpy()
    except Exception as e:
        attempts.append("arcpy import failed: %s" % e)
        _state.update(mxd=None, mode=None, attempts=attempts)
        return None, None, attempts
    # 策略 1：CURRENT —— ArcMap Python 窗口内的官方实时入口
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        if _looks_like_mxd(mxd):
            attempts.append('accepted MapDocument("CURRENT")')
            _state.update(mxd=mxd, mode="live:CURRENT", attempts=attempts)
            return mxd, "live:CURRENT", attempts
        attempts.append('MapDocument("CURRENT") returned unexpected object')
    except Exception as e:
        attempts.append('MapDocument("CURRENT") failed: %s' % e)
    # 策略 2：注入的全局变量
    import __main__
    for scope_name, scope in (("bridge_globals", globals()), ("__main__", vars(__main__))):
        for key in ("mxd", "current_mxd", "currentMxd", "map_document", "doc"):
            obj = scope.get(key)
            if _looks_like_mxd(obj):
                attempts.append("accepted %s.%s" % (scope_name, key))
                mode = "live:global:%s.%s" % (scope_name, key)
                _state.update(mxd=obj, mode=mode, attempts=attempts)
                return obj, mode, attempts
            elif obj is not None:
                attempts.append("rejected %s.%s (not a MapDocument)" % (scope_name, key))
    # 策略 3：文件回退（只能看到已保存状态）
    path = os.environ.get("ARCMAP_LIVE_MXD_PATH")
    if path and os.path.isfile(path):
        try:
            mxd = arcpy.mapping.MapDocument(path)
            attempts.append("file-fallback opened %s" % path)
            _state.update(mxd=mxd, mode="file-fallback", attempts=attempts)
            return mxd, "file-fallback", attempts
        except Exception as e:
            attempts.append("file-fallback failed: %s" % e)
    _state.update(mxd=None, mode=None, attempts=attempts)
    return None, None, attempts


def _require_mxd():
    mxd, mode, attempts = discover_document()
    if mxd is None:
        raise RuntimeError("LIVE_DOCUMENT_NOT_FOUND: 未发现当前地图文档；attempts=%s" % (attempts,))
    return mxd, mode


# ------------------------------------------------------------ 盘点助手
def _dataframes(arcpy, mxd):
    try:
        return list(arcpy.mapping.ListDataFrames(mxd))
    except Exception:
        return []


def _layers(arcpy, mxd, df):
    try:
        return list(arcpy.mapping.ListLayers(mxd, "", df))
    except Exception:
        return []


def _layer_entry(ly):
    entry = {"name": _safe_str(getattr(ly, "name", None))}
    for attr, key in (("dataSource", "data_source"), ("visible", "visible"),
                      ("isBroken", "is_broken"), ("isGroupLayer", "is_group_layer")):
        try:
            entry[key] = getattr(ly, attr)
        except Exception:
            entry[key] = None
    if entry.get("data_source") is not None:
        entry["data_source"] = _safe_str(entry["data_source"])
    return entry


def _extent_of_df(df):
    try:
        ext = df.extent
        return {"xmin": ext.XMin, "ymin": ext.YMin, "xmax": ext.XMax, "ymax": ext.YMax}
    except Exception:
        return None


def _find_layer(arcpy, mxd, selector, dataframe=None):
    """按图层名或全局下标定位；返回 (layer, df, index, 全部图层名)。"""
    if isinstance(selector, str) and selector.isdigit():
        selector = int(selector)
    elif isinstance(selector, _text) and selector.isdigit():
        selector = int(selector)
    flat_index = -1
    names = []
    found = (None, None, None)
    for df in _dataframes(arcpy, mxd):
        df_name = _safe_str(getattr(df, "name", None))
        if dataframe is not None and df_name != dataframe:
            continue
        for ly in _layers(arcpy, mxd, df):
            flat_index += 1
            nm = _safe_str(getattr(ly, "name", None))
            names.append(nm)
            if isinstance(selector, int) and selector == flat_index:
                found = (ly, df, flat_index)
            elif isinstance(selector, (str, _text)) and nm == selector:
                found = (ly, df, flat_index)
    return found[0], found[1], found[2], names


def _refresh_view(arcpy, notes):
    """缩放/显隐后刷新活动视图；多策略，失败只记录不推翻结果。"""
    for mod_name in ("arcpy", "arcpy.mapping"):
        try:
            mod = __import__(mod_name)
            fn = getattr(mod, "RefreshActiveView", None)
            if callable(fn):
                fn()
                return mod_name + ".RefreshActiveView"
        except Exception as e:
            notes.append("RefreshActiveView via %s failed: %s" % (mod_name, e))
    return None


# ------------------------------------------------------------ 只读工具
def tool_ping(args):
    return {"pong": True, "bridge": "arcmap-live-bridge/0.2",
            "python": sys.version.split()[0]}


def tool_discover(args):
    mxd, mode, attempts = discover_document(force=True)
    report = {"mode": mode, "attempts": attempts, "document_found": mxd is not None}
    if mxd is not None:
        report["document_type"] = _safe_str(type(mxd))
        report["file_path"] = _safe_str(getattr(mxd, "filePath", None))
        report["document_methods"] = _methods_hint(mxd, 200)
    try:
        arcpy = _import_arcpy()
        report["arcpy_file"] = _safe_str(getattr(arcpy, "__file__", "unknown"))
        try:
            info = arcpy.GetInstallInfo()
            report["arcgis_product"] = _safe_str(info.get("ProductName"))
            report["arcgis_version"] = _safe_str(info.get("Version"))
        except Exception as e:
            report["install_info_error"] = _safe_str(e)
        report["mapping_names"] = [n for n in dir(arcpy.mapping)
                                   if n.startswith(("List", "Export", "MapDocument", "Refresh"))]
    except Exception as e:
        report["arcpy_error"] = _safe_str(e)
    import __main__
    report["main_globals"] = [k for k in vars(__main__).keys() if not k.startswith("_")][:100]
    return report


def tool_document_info(args):
    arcpy = _import_arcpy()
    mxd, mode = _require_mxd()
    info = {"mode": mode,
            "file_path": _safe_str(getattr(mxd, "filePath", None)),
            "active_view": _safe_str(getattr(mxd, "activeView", None))}
    try:
        ps = mxd.pageSize
        info["page_size"] = {"width": ps.width, "height": ps.height}
    except Exception:
        info["page_size"] = None
    frames = _dataframes(arcpy, mxd)
    info["dataframe_count"] = len(frames)
    info["layer_count"] = sum(len(_layers(arcpy, mxd, df)) for df in frames)
    return info


def tool_list_dataframes(args):
    arcpy = _import_arcpy()
    mxd, mode = _require_mxd()
    out = []
    for df in _dataframes(arcpy, mxd):
        entry = {"name": _safe_str(getattr(df, "name", None)),
                 "extent": _extent_of_df(df),
                 "layer_count": len(_layers(arcpy, mxd, df))}
        try:
            entry["scale"] = df.scale
        except Exception:
            entry["scale"] = None
        try:
            sr = df.spatialReference
            entry["spatial_reference"] = _safe_str(getattr(sr, "name", None)) if sr else None
        except Exception:
            entry["spatial_reference"] = None
        out.append(entry)
    return {"mode": mode, "dataframes": out}


def tool_list_layers(args):
    arcpy = _import_arcpy()
    mxd, mode = _require_mxd()
    wanted = args.get("dataframe")
    out = []
    for df in _dataframes(arcpy, mxd):
        df_name = _safe_str(getattr(df, "name", None))
        if wanted is not None and df_name != wanted:
            continue
        for i, ly in enumerate(_layers(arcpy, mxd, df)):
            entry = _layer_entry(ly)
            entry["dataframe"] = df_name
            entry["index_in_frame"] = i
            out.append(entry)
    return {"mode": mode, "layers": out}


def tool_list_tables(args):
    arcpy = _import_arcpy()
    mxd, mode = _require_mxd()
    out = []
    try:
        views = list(arcpy.mapping.ListTableViews(mxd))
    except Exception as e:
        raise RuntimeError("NOT_SUPPORTED: ListTableViews 不可用: %s；mapping_names=%s"
                           % (e, [n for n in dir(arcpy.mapping) if n.startswith("List")]))
    for tv in views:
        entry = {"name": _safe_str(getattr(tv, "name", None))}
        try:
            entry["data_source"] = _safe_str(tv.dataSource)
        except Exception:
            entry["data_source"] = None
        out.append(entry)
    return {"mode": mode, "table_views": out}


# ------------------------------------------------------------ 视图级工具
def tool_set_layer_visible(args):
    """视图级：设置图层显隐（只改显示状态、可逆，无 confirm 闸）。"""
    arcpy = _import_arcpy()
    mxd, mode = _require_mxd()
    selector = args.get("layer")
    visible = args.get("visible")
    if selector is None or not isinstance(visible, bool):
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名或下标）与 visible（布尔）")
    layer, df, idx, names = _find_layer(arcpy, mxd, selector, args.get("dataframe"))
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s" % (selector, names))
    try:
        layer.visible = visible
        via = "attr:visible"
    except Exception as e:
        raise RuntimeError("NOT_SUPPORTED: 图层 visible 属性不可写: %s；layer_methods=%s"
                           % (e, _methods_hint(layer)))
    notes = []
    refresh_via = _refresh_view(arcpy, notes)
    return {"mode": mode, "layer": names[idx], "index": idx,
            "dataframe": _safe_str(getattr(df, "name", None)),
            "visible_set_to": visible,
            "visible_now": getattr(layer, "visible", None),
            "via": via, "refresh_via": refresh_via}


def tool_zoom_to_layer(args):
    """视图级：把数据框视图缩放到图层范围，设置 dataFrame.extent 后刷新。"""
    arcpy = _import_arcpy()
    mxd, mode = _require_mxd()
    selector = args.get("layer")
    if selector is None:
        raise RuntimeError("BAD_ARGS: 必须提供 layer（图层名或下标）")
    layer, df, idx, names = _find_layer(arcpy, mxd, selector, args.get("dataframe"))
    if layer is None:
        raise RuntimeError("LAYER_NOT_FOUND: 图层 %r 不存在；可用图层: %s" % (selector, names))
    try:
        extent = layer.getExtent()
    except Exception as e:
        raise RuntimeError("NOT_SUPPORTED: 图层范围不可得: %s；layer_methods=%s"
                           % (e, _methods_hint(layer)))
    try:
        df.extent = extent
        via = "dataFrame.extent = layer.getExtent()"
    except Exception as e:
        raise RuntimeError("ZOOM_FAILED: 无法把范围设置到数据框: %s" % e)
    notes = []
    refresh_via = _refresh_view(arcpy, notes)
    return {"zoomed": True, "mode": mode, "layer": names[idx], "index": idx,
            "dataframe": _safe_str(getattr(df, "name", None)), "via": via,
            "extent": {"xmin": extent.XMin, "ymin": extent.YMin,
                       "xmax": extent.XMax, "ymax": extent.YMax},
            "refresh_via": refresh_via}


# ------------------------------------------------------------ 出图 / 保存
def tool_export_map_image(args):
    """只读出文件：把当前文档导出为 PNG 到指定路径；以文件真实落盘为准。"""
    arcpy = _import_arcpy()
    mxd, mode = _require_mxd()
    out_path = args.get("out_path")
    if not out_path:
        raise RuntimeError("BAD_ARGS: 必须提供 out_path（PNG 输出路径）")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(out_dir):
        raise RuntimeError("BAD_ARGS: 输出目录不存在: %s" % out_dir)
    resolution = args.get("resolution")
    frames = _dataframes(arcpy, mxd)
    notes = []
    attempts = []
    attempts.append((("PAGE_LAYOUT",), {}, "ExportToPNG(mxd, path, 'PAGE_LAYOUT')"))
    attempts.append(((), {}, "ExportToPNG(mxd, path)"))
    if frames:
        attempts.append(((frames[0],), {}, "ExportToPNG(mxd, path, dataFrame)"))
    if isinstance(resolution, int):
        attempts.append((("PAGE_LAYOUT",), {"resolution": resolution},
                         "ExportToPNG(mxd, path, 'PAGE_LAYOUT', resolution=%d)" % resolution))
    for extra_args, kwargs, label in attempts:
        try:
            arcpy.mapping.ExportToPNG(mxd, out_path, *extra_args, **kwargs)
        except Exception as e:
            notes.append("%s failed: %s" % (label, e))
            continue
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return {"exported": True, "mode": mode, "via": label,
                    "path": out_path, "bytes": os.path.getsize(out_path)}
        notes.append("%s 调用未报错但文件未落盘，不算成功" % label)
    raise RuntimeError("NOT_SUPPORTED: 全部导出策略失败或未落盘；notes=%s" % (notes,))


def tool_save_document(args):
    """写类：保存当前地图文档。须 confirm=true。"""
    if args.get("confirm") is not True:
        return {"saved": False, "reason": "save_document 需要 confirm=true 显式确认"}
    mxd, mode = _require_mxd()
    notes = []
    try:
        mxd.save()
        return {"saved": True, "mode": mode, "via": "mxd.save()",
                "file_path": _safe_str(getattr(mxd, "filePath", None))}
    except Exception as e:
        notes.append("mxd.save() failed: %s" % e)
    fp = getattr(mxd, "filePath", None)
    if fp:
        try:
            mxd.saveACopy(fp)
            return {"saved": True, "mode": mode, "via": "mxd.saveACopy(filePath)",
                    "file_path": _safe_str(fp),
                    "note": "save() 失败后以 saveACopy 写回原路径，效果等同保存，"
                            "但请在界面核对文档状态"}
        except Exception as e:
            notes.append("mxd.saveACopy failed: %s" % e)
    raise RuntimeError("SAVE_FAILED: 保存全部策略失败；notes=%s" % (notes,))


TOOLS = {
    "ping": tool_ping,
    "discover": tool_discover,
    "document_info": tool_document_info,
    "list_dataframes": tool_list_dataframes,
    "list_layers": tool_list_layers,
    "list_tables": tool_list_tables,
    "set_layer_visible": tool_set_layer_visible,
    "zoom_to_layer": tool_zoom_to_layer,
    "export_map_image": tool_export_map_image,
    "save_document": tool_save_document,
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
    with open(TOKEN_FILE, "w") as f:
        f.write(TOKEN)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    _log("[arcmap-live-bridge] listening on %s:%d token_file=%s" % (HOST, PORT, TOKEN_FILE))
    _log("[arcmap-live-bridge] tools: %s" % ", ".join(sorted(TOOLS)))
    while True:
        conn, _addr = srv.accept()
        try:
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
            payload = json.dumps(_to_text(resp), ensure_ascii=False)
            if not isinstance(payload, bytes):
                payload = payload.encode("utf-8")
            conn.sendall(payload + b"\n")
        finally:
            try:
                conn.close()
            except Exception:
                pass


def start(blocking=True):
    if blocking:
        serve()
    else:
        t = threading.Thread(target=serve)
        t.daemon = True
        t.start()
        return t


# 启动方式判定：
# - 环境变量 ARCMAP_BRIDGE_BLOCKING=1/0 显式指定时以它为准；
# - 以脚本文件方式运行（命令行/自检）时 __file__ 存在 → 前台阻塞服务；
# - 在 ArcMap Python 窗口里 execfile/exec 注入时 __file__ 通常不存在
#   → 起后台线程，不阻塞控制台。
_env_blocking = os.environ.get("ARCMAP_BRIDGE_BLOCKING")
if _env_blocking in ("1", "true", "yes"):
    start(blocking=True)
elif _env_blocking in ("0", "false", "no"):
    start(blocking=False)
elif globals().get("__file__"):
    start(blocking=True)
else:
    start(blocking=False)
