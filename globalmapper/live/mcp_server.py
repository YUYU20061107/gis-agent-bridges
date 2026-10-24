# -*- coding: utf-8 -*-
"""
mcp_server.py — Global Mapper MCP 服务端（stdio，纯标准库，v0.2）

与本系列其他桥不同：Global Mapper 没有可常驻的应用内桥形态，本服务端
直接在自己的进程里 import globalmapper 模块（仅 Global Mapper Pro 提供）
执行工具。两个运行位置决定两种能力形态，工具会如实回报当前 context：

  - headless（外部 Python 运行，模块可导入但没有应用已加载的图层）：
    可打开 .gmw 列图层、可导出图；图层显隐/缩放属于主视图操作，
    一律结构化返回 NOT_IN_MAIN_VIEW_CONTEXT，绝不假装执行。
  - 脚本上下文（在 Global Mapper 桌面 Script Editor 中以
    “Run Script in the Context of the Main View”方式启动本服务端，
    或模块报告应用已加载图层）：显隐/缩放才允许尝试。
    这只是“半实时”：没有常驻桥、没有推送，界面刷新时机取决于 Global
    Mapper 本身；本服务端不宣称完整实时接入。

工具（7 个）：
  只读：globalmapper_ping / globalmapper_discover /
        globalmapper_workspace_info / globalmapper_list_layers
  视图级（仅脚本上下文）：globalmapper_set_layer_visible /
        globalmapper_zoom_to_layer
  只读出文件：globalmapper_export_workspace_image（落盘且字节>0 才算成功）

globalmapper 的 API 随版本差异大：全部操作多策略尝试，命中函数名记入
via 字段；调不通返回结构化错误（ok=false + error_code），不许粉饰成功。

环境变量：
  GM_BRIDGE_CONTEXT   设为 main-view 可声明当前处于主视图脚本上下文
                      （仅在确实从 Script Editor 主视图上下文启动时设置）
  GM_BRIDGE_TOKEN     设置后，每次 tools/call 必须在 arguments 里带
                      _token 且与之相等，否则以 BAD_TOKEN 拒绝
日志写 stderr，stdout 只走 MCP 协议。
"""
import io
import json
import os
import sys
import time

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "globalmapper-bridge"
SERVER_VERSION = "0.2.0"

# ------------------------------------------------------------ API 候选表
VERSION_ATTRS = ["__version__", "VERSION", "version"]
VERSION_FUNCS = ["GM_GetVersion", "GM_GetVersionInfo", "GM_GetGlobalMapperVersion",
                 "GM_GetProductVersion", "GetVersion"]
LOAD_FUNCS = ["GM_LoadWorkspace", "GM_LoadLayer", "GM_LoadLayerList",
              "GM_OpenWorkspace", "GM_LoadLayers"]
LAYER_LIST_FUNCS = ["GM_GetLayerList", "GM_GetLoadedLayerList", "GM_GetAllLayers",
                    "GM_ListLayers", "GM_GetLayers"]
LAYER_INFO_FUNCS = ["GM_GetLayerInfo", "GM_GetLayerDescription", "GM_GetLayerName"]
LAYER_NAME_ATTRS = ["m_strName", "Name", "name", "m_strDesc", "Description",
                    "description", "m_strFilename", "Filename", "filename"]
VISIBLE_GET_FUNCS = ["GM_GetLayerVisible", "GM_IsLayerVisible",
                     "GM_GetLayerEnabled", "GM_IsLayerEnabled"]
SHOW_FUNCS = ["GM_ShowLayer", "GM_SetLayerVisible", "GM_SetLayerEnabled",
              "GM_EnableLayer"]
HIDE_FUNCS = ["GM_HideLayer", "GM_SetLayerVisible", "GM_SetLayerEnabled",
              "GM_DisableLayer"]
ZOOM_DIRECT_FUNCS = ["GM_ZoomToLayer", "GM_SetViewToLayer", "GM_ViewLayer"]
LAYER_BOUNDS_FUNCS = ["GM_GetLayerBoundingBox", "GM_GetLayerBounds",
                      "GM_GetLayerExtent"]
SET_VIEW_FUNCS = ["GM_SetDisplayExtent", "GM_SetViewRect", "GM_SetViewBounds",
                  "GM_SetDisplayRect"]
EXPORT_FUNCS = ["GM_ExportRaster", "GM_ExportRasterEx", "GM_ExportWebFormat",
                "GM_ExportPackage", "GM_ExportMapImage"]

_state = {"module": None, "module_error": None, "module_tried": False,
          "workspace_path": None, "opened_via": None, "handles": [],
          "context": None, "context_evidence": []}


def log(*a):
    print("[globalmapper-mcp]", *a, file=sys.stderr, flush=True)

# ---- 序列化净化（与 arcmap 已修版同口径） ----
try:
    _TEXT = unicode  # noqa: F821
except NameError:
    _TEXT = str


def _dec(b):
    """bytes -> 文本。解码顺序：UTF-8 -> 系统文件系统编码 -> GBK -> latin-1。"""
    if isinstance(b, _TEXT):
        return b
    if not isinstance(b, (bytes, bytearray)):
        return "%s" % (b,)
    try:
        return bytes(b).decode("utf-8")
    except Exception:
        pass
    for enc in (sys.getfilesystemencoding(), "gbk", "latin-1"):
        if not enc:
            continue
        try:
            return bytes(b).decode(enc)
        except Exception:
            continue
    return bytes(b).decode("utf-8", "replace")


def _to_text(obj):
    """递归净化待 JSON 序列化的对象：dict/list 递归，bytes 解码为文本，
    其余不可序列化的对象转 str，保证 dumps 不会因为厂商 API 返回
    bytes / 异类对象而 TypeError 崩溃。"""
    if isinstance(obj, dict):
        return dict((_to_text(k), _to_text(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [_to_text(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return _dec(obj)
    if obj is None or isinstance(obj, (_TEXT, bool, int, float)):
        return obj
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return "%s" % (obj,)



def _lock_stdio_utf8():
    """把 stdin/stdout 锁定为 UTF-8：中文 Windows 的管道默认 GBK 编码会把
    MCP 协议里的中文写成 GBK 字节，客户端按 UTF-8 解码直接失败。
    只在 main() 里调用一次；已是 UTF-8 或无 buffer 时跳过，避免重复包装。"""
    for _name in ("stdout", "stdin"):
        _stream = getattr(sys, _name, None)
        _buf = getattr(_stream, "buffer", None)
        if _buf is None or getattr(_stream, "encoding", None) == "utf-8":
            continue
        try:
            setattr(sys, _name, io.TextIOWrapper(_buf, encoding="utf-8",
                                                 errors="replace"))
        except Exception:
            pass



class ToolError(Exception):
    def __init__(self, error_code, message, **extra):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.extra = extra


def _gm():
    if not _state["module_tried"]:
        _state["module_tried"] = True
        try:
            import globalmapper
            _state["module"] = globalmapper
        except Exception as e:
            _state["module_error"] = str(e)
    return _state["module"]


def _require_module():
    mod = _gm()
    if mod is None:
        raise ToolError(
            "GM_MODULE_NOT_AVAILABLE",
            "globalmapper 模块不可用: %s。该模块仅随 Global Mapper Pro "
            "提供；请在 Pro 的 Python 环境中运行本服务端，或先跑 "
            "scripts/probe_api.py 确认本机形态" % _state["module_error"])
    return mod


def _call_first(mod, names, *args):
    attempts = []
    for name in names:
        fn = getattr(mod, name, None)
        if not callable(fn):
            attempts.append("%s: not present" % name)
            continue
        try:
            return fn(*args), name, attempts
        except Exception as e:
            attempts.append("%s: %s" % (name, e))
    return None, None, attempts


def _flatten_handles(result):
    if result is None:
        return [], "none"
    if isinstance(result, (list, tuple)):
        items = [x for x in result if x is not None]
        return items, "sequence(%d)" % len(items)
    return [result], "single:%s" % type(result).__name__


def _module_version(mod):
    for attr in VERSION_ATTRS:
        if hasattr(mod, attr):
            val = getattr(mod, attr)
            if not callable(val) and val:
                return str(val), "attr:" + attr
    val, via, _att = _call_first(mod, VERSION_FUNCS)
    if val is not None:
        return str(val)[:120], via
    return None, None


def _candidate_hits(mod):
    groups = {"version": VERSION_FUNCS, "load": LOAD_FUNCS,
              "layer_list": LAYER_LIST_FUNCS, "layer_info": LAYER_INFO_FUNCS,
              "visible_get": VISIBLE_GET_FUNCS, "show": SHOW_FUNCS,
              "hide": HIDE_FUNCS, "zoom": ZOOM_DIRECT_FUNCS + LAYER_BOUNDS_FUNCS
              + SET_VIEW_FUNCS, "export": EXPORT_FUNCS}
    return {g: [n for n in cands if callable(getattr(mod, n, None))]
            for g, cands in groups.items()}


def _preloaded_handles(mod):
    """探测应用是否已加载图层（脚本上下文的证据），返回 (handles, via)。"""
    listed, via, _att = _call_first(mod, LAYER_LIST_FUNCS)
    if listed is None:
        return [], None
    handles, _shape = _flatten_handles(listed)
    return handles, via


def _detect_context(force=False):
    if _state["context"] is not None and not force:
        return _state["context"]
    evidence = []
    ctx = "headless"
    if os.environ.get("GM_BRIDGE_CONTEXT", "").strip().lower() == "main-view":
        ctx = "script-main-view"
        evidence.append("GM_BRIDGE_CONTEXT=main-view declared by launcher")
    else:
        mod = _gm()
        if mod is not None:
            handles, via = _preloaded_handles(mod)
            if handles:
                ctx = "script-context-suspected"
                evidence.append("layer-list candidate %s reports %d preloaded "
                                "layer(s) without this server loading anything"
                                % (via, len(handles)))
    _state["context"] = ctx
    _state["context_evidence"] = evidence
    return ctx


def _layer_name(mod, handle):
    info, via, _att = _call_first(mod, LAYER_INFO_FUNCS, handle)
    if info is not None:
        if isinstance(info, str):
            return info, via
        for attr in LAYER_NAME_ATTRS:
            if hasattr(info, attr):
                val = getattr(info, attr)
                if callable(val):
                    try:
                        val = val()
                    except Exception:
                        continue
                if val:
                    return str(val), "%s.%s" % (via, attr)
        return str(info)[:120], via + "(repr)"
    if isinstance(handle, str):
        return handle, "handle-as-name"
    return None, None


def _layer_visible(mod, handle):
    val, _via, _att = _call_first(mod, VISIBLE_GET_FUNCS, handle)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return None


def _enumerate_layers(mod):
    """当前可枚举的图层：优先本服务端打开工作区的 handles，
    其次应用预加载图层。返回 (handles, source)。"""
    if _state["handles"]:
        return list(_state["handles"]), "opened-workspace"
    handles, _via = _preloaded_handles(mod)
    if handles:
        return handles, "app-preloaded"
    return [], "none"


def _open_workspace(mod, path):
    if not os.path.isfile(path):
        raise ToolError("FILE_NOT_FOUND", "工作区文件不存在: %s" % path)
    loaded, via, attempts = _call_first(mod, LOAD_FUNCS, path)
    if via is None:
        raise ToolError("OPEN_WORKSPACE_FAILED", "全部加载候选均失败",
                        attempts=attempts)
    handles, _shape = _flatten_handles(loaded)
    if len(handles) <= 1:
        listed, list_via, _a = _call_first(mod, LAYER_LIST_FUNCS)
        if listed is not None:
            handles2, _s2 = _flatten_handles(listed)
            if len(handles2) > len(handles):
                handles = handles2
                via = "%s+%s" % (via, list_via)
    _state["workspace_path"] = path
    _state["opened_via"] = via
    _state["handles"] = handles
    return via


def _resolve_layer(mod, layer_arg):
    handles, source = _enumerate_layers(mod)
    if not handles:
        raise ToolError(
            "NO_LAYERS_LOADED",
            "当前没有可操作的图层：先用 list_layers 的 workspace 参数打开 "
            ".gmw，或在本工具的脚本上下文中确认应用已加载图层")
    if isinstance(layer_arg, int):
        idx = layer_arg
    elif isinstance(layer_arg, str) and layer_arg.isdigit():
        idx = int(layer_arg)
    else:
        idx = None
    if idx is not None:
        if 0 <= idx < len(handles):
            return handles[idx], idx
        raise ToolError("LAYER_NOT_FOUND", "图层下标越界: %d（共 %d 层）"
                        % (idx, len(handles)))
    for i, handle in enumerate(handles):
        name, _via = _layer_name(mod, handle)
        if name is not None and name == layer_arg:
            return handle, i
    raise ToolError("LAYER_NOT_FOUND",
                    "按名称找不到图层: %s（source=%s）" % (layer_arg, source))


def _require_main_view_context():
    ctx = _detect_context()
    if ctx not in ("script-main-view", "script-context-suspected"):
        raise ToolError(
            "NOT_IN_MAIN_VIEW_CONTEXT",
            "当前 context=%s：图层显隐/缩放是 Global Mapper 主视图操作，"
            "无头模式下模块没有可操作的主视图。本工具只在脚本上下文"
            "（Script Editor 勾选 Run Script in the Context of the Main "
            "View 启动，或模块报告应用已加载图层）下才尝试执行" % ctx,
            context=ctx)
    return ctx


# ------------------------------------------------------------------- tools
def tool_ping(args):
    mod = _gm()
    return {"pong": True, "bridge": "globalmapper-bridge/0.2",
            "module_found": mod is not None,
            "context": _detect_context()}


def tool_discover(args):
    mod = _gm()
    result = {"module_found": mod is not None,
              "context": _detect_context(force=True),
              "context_evidence": _state["context_evidence"],
              "notes": ["本桥为半实时：无常驻应用内桥；视图类工具仅在"
                        "脚本上下文下尝试，见 live/LIVE.md"]}
    if mod is None:
        result["module_error"] = _state["module_error"]
        return result
    result["module_file"] = getattr(mod, "__file__", "unknown")
    version, via = _module_version(mod)
    result["module_version"] = version
    result["module_version_via"] = via
    result["function_candidates_hit"] = _candidate_hits(mod)
    return result


def tool_workspace_info(args):
    mod = _gm()
    info = {"context": _detect_context(),
            "context_evidence": _state["context_evidence"],
            "module_found": mod is not None,
            "workspace_path": _state["workspace_path"],
            "opened_via": _state["opened_via"],
            "layer_count": None}
    if mod is not None:
        version, _via = _module_version(mod)
        info["module_version"] = version
        handles, source = _enumerate_layers(mod)
        info["layer_count"] = len(handles)
        info["layer_source"] = source
    return info


def tool_list_layers(args):
    mod = _require_module()
    workspace = args.get("workspace")
    if workspace:
        _open_workspace(mod, workspace)
    handles, source = _enumerate_layers(mod)
    layers = []
    for i, handle in enumerate(handles):
        name, name_via = _layer_name(mod, handle)
        layers.append({"index": i, "name": name, "name_via": name_via,
                       "visible": _layer_visible(mod, handle),
                       "handle_repr": str(handle)[:80]})
    return {"workspace": _state["workspace_path"], "context": _detect_context(),
            "layer_source": source, "layer_count": len(layers),
            "layers": layers,
            "complete": source != "none"}


def tool_set_layer_visible(args):
    mod = _require_module()
    ctx = _require_main_view_context()
    layer_arg = args.get("layer")
    visible = args.get("visible")
    if layer_arg is None or not isinstance(visible, bool):
        raise ToolError("BAD_ARGUMENTS", "需要 layer（名称或下标）与 visible（布尔）")
    handle, idx = _resolve_layer(mod, layer_arg)
    candidates = SHOW_FUNCS if visible else HIDE_FUNCS
    attempts = []
    for name in candidates:
        fn = getattr(mod, name, None)
        if not callable(fn):
            attempts.append("%s: not present" % name)
            continue
        for call_args in ((handle, visible), (handle,)):
            try:
                fn(*call_args)
                now = _layer_visible(mod, handle)
                return {"layer_index": idx, "visible_set": visible,
                        "visible_now": now, "via": name,
                        "via_signature": "%s(%s)" % (
                            name, ", ".join(["handle", "visible"][:len(call_args)])),
                        "context": ctx}
            except Exception as e:
                attempts.append("%s%r: %s" % (name, call_args, e))
    raise ToolError("NOT_SUPPORTED", "全部显隐候选均失败（本机版本 API 形态待校准）",
                    attempts=attempts)


def tool_zoom_to_layer(args):
    mod = _require_module()
    ctx = _require_main_view_context()
    layer_arg = args.get("layer")
    if layer_arg is None:
        raise ToolError("BAD_ARGUMENTS", "需要 layer（名称或下标）")
    handle, idx = _resolve_layer(mod, layer_arg)
    res, via, attempts = _call_first(mod, ZOOM_DIRECT_FUNCS, handle)
    if via is not None:
        return {"layer_index": idx, "zoomed": True, "via": via, "context": ctx}
    # 退化路线：取图层范围 -> 设置视图范围
    bbox, bbox_via, att2 = _call_first(mod, LAYER_BOUNDS_FUNCS, handle)
    attempts.extend(att2)
    rect = None
    if bbox is not None:
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                rect = [float(bbox[0]), float(bbox[1]),
                        float(bbox[2]), float(bbox[3])]
            except Exception:
                rect = None
        else:
            vals = []
            for attr in ("min_x", "minX", "left", "x_min", "m_minX",
                         "min_y", "minY", "bottom", "y_min", "m_minY",
                         "max_x", "maxX", "right", "x_max", "m_maxX",
                         "max_y", "maxY", "top", "y_max", "m_maxY"):
                if hasattr(bbox, attr):
                    vals.append(attr)
            if len(vals) >= 4:
                try:
                    rect = [float(getattr(bbox, vals[i])) for i in range(4)]
                except Exception:
                    rect = None
    if rect is not None:
        for name in SET_VIEW_FUNCS:
            fn = getattr(mod, name, None)
            if not callable(fn):
                attempts.append("%s: not present" % name)
                continue
            for call_args in ((rect,), tuple(rect)):
                try:
                    fn(*call_args)
                    return {"layer_index": idx, "zoomed": True,
                            "via": "%s via bounds %s" % (name, bbox_via),
                            "rect": rect, "context": ctx}
                except Exception as e:
                    attempts.append("%s: %s" % (name, e))
    raise ToolError("NOT_SUPPORTED",
                    "直接缩放与“范围->设视图”两条路线均未走通"
                    "（Global Mapper 公开脚本 API 可能本就没有缩放主视图的"
                    "入口，属预期内的结构化失败）",
                    attempts=attempts)


def tool_export_workspace_image(args):
    mod = _require_module()
    out_path = args.get("out_path")
    if not out_path:
        raise ToolError("BAD_ARGUMENTS", "需要 out_path（导出文件路径）")
    workspace = args.get("workspace")
    if workspace:
        _open_workspace(mod, workspace)
    handles, source = _enumerate_layers(mod)
    if not handles:
        raise ToolError("NO_LAYERS_LOADED",
                        "没有已加载图层可导出：先传 workspace 打开 .gmw，"
                        "或在脚本上下文中确认应用已加载图层")
    attempts = []
    for name in EXPORT_FUNCS:
        fn = getattr(mod, name, None)
        if not callable(fn):
            attempts.append("%s: not present" % name)
            continue
        for call_args in ((out_path,), (out_path, None)):
            start = time.time()
            try:
                fn(*call_args)
            except Exception as e:
                attempts.append("%s%r: %s" % (name, call_args, e))
                continue
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0 \
                    and os.path.getmtime(out_path) >= start - 1:
                return {"out_path": out_path,
                        "bytes": os.path.getsize(out_path),
                        "via": name, "layer_source": source}
            attempts.append("%s%r: called but no fresh non-empty file"
                            % (name, call_args))
    raise ToolError("EXPORT_FAILED",
                    "全部导出候选均未产生落盘文件（签名待按本机版本校准）",
                    attempts=attempts)


# ---------------------------------------------------------------- MCP glue
_STR = {"type": "string"}
_BOOL = {"type": "boolean"}

TOOL_DEFS = [
    ("globalmapper_ping", "连通性检查：服务端在线、模块可用性与当前上下文", {},
     tool_ping),
    ("globalmapper_discover", "发现 globalmapper 模块、版本、候选函数命中与运行上下文（校准用）", {},
     tool_discover),
    ("globalmapper_workspace_info", "当前工作区概览：上下文、已打开工作区、图层数", {},
     tool_workspace_info),
    ("globalmapper_list_layers", "列图层（名称、显隐可得时）；可传 workspace 先打开某个 .gmw",
     {"workspace": dict(_STR, description="可选：.gmw 路径，先打开再列")},
     tool_list_layers),
    ("globalmapper_set_layer_visible", "【视图级·仅脚本上下文】设置图层显隐；无头模式返回 NOT_IN_MAIN_VIEW_CONTEXT",
     {"layer": dict(_STR, description="图层名或下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示，false=隐藏")},
     tool_set_layer_visible),
    ("globalmapper_zoom_to_layer", "【视图级·仅脚本上下文】主视图缩放到图层范围；无头模式返回 NOT_IN_MAIN_VIEW_CONTEXT",
     {"layer": dict(_STR, description="图层名或下标（数字字符串）")},
     tool_zoom_to_layer),
    ("globalmapper_export_workspace_image", "把当前已加载图层导出为栅格图片到 out_path；以文件落盘且字节>0 为准",
     {"out_path": dict(_STR, description="输出文件路径（必填）"),
      "workspace": dict(_STR, description="可选：.gmw 路径，先打开再导出")},
     tool_export_workspace_image),
]

TOOLS = {name: fn for name, _d, _p, fn in TOOL_DEFS}


def tools_list():
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props, _fn in TOOL_DEFS]


def _error_content(error_code, message, **extra):
    obj = {"ok": False, "error_code": error_code, "message": message}
    obj.update(extra)
    return {"content": [{"type": "text",
                         "text": json.dumps(_to_text(obj), ensure_ascii=False, indent=2)}],
            "isError": True}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools_list()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = dict(params.get("arguments") or {})
        expected = os.environ.get("GM_BRIDGE_TOKEN")
        if expected:
            if args.pop("_token", None) != expected:
                return {"jsonrpc": "2.0", "id": mid, "result":
                        _error_content("BAD_TOKEN",
                                       "GM_BRIDGE_TOKEN 已设置，调用须带匹配的 _token")}
        else:
            args.pop("_token", None)
        fn = TOOLS.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid, "result":
                    _error_content("UNKNOWN_TOOL", "unknown tool: %s" % name)}
        try:
            result = fn(args)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(_to_text(result), ensure_ascii=False,
                                                indent=2)}],
                "isError": False}}
        except ToolError as e:
            return {"jsonrpc": "2.0", "id": mid, "result":
                    _error_content(e.error_code, e.message, **e.extra)}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result":
                    _error_content("TOOL_FAILED", "tool failed: %s" % e)}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    _lock_stdio_utf8()
    log("starting; token gate %s" %
        ("on" if os.environ.get("GM_BRIDGE_TOKEN") else "off"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:
            log("bad json:", e)
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(_to_text(resp), ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
