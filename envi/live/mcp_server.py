# -*- coding: utf-8 -*-
"""
mcp_server.py — ENVI 无头桥 MCP 服务端（stdio，纯标准库，v0.2）

与本系列其他桥不同：ENVI 没有官方支持的"附着到已打开 GUI 会话"的通道，
因此本包**没有应用内桥**。本服务端直接在宿主 Python 里干活：
  - 栅格盘点优先走纯 Python 的 .hdr 解析（不需要 ENVI、不需要许可）；
  - 需要真跑算法时，惰性 import idlpy 并启动一个 HEADLESS ENVI 会话
    （IDL.ENVI(HEADLESS=1)），经 ENVITask 体系执行任务。
工具：
  只读：envi_ping / envi_discover / envi_raster_info /
        envi_list_tasks / envi_describe_task
  写类（须 confirm=true）：envi_run_task / envi_export_raster_subset
没有 ENVI 的机器上，只读盘点照常工作；list/describe/run/export 会如实
返回结构化 ENVI_NOT_AVAILABLE，绝不假装执行过任务。

可选安全闸：设置环境变量 ENVI_BRIDGE_TOKEN 后，tools/call 必须在
params._meta.token 里带对同一 token，否则返回 BAD_TOKEN。
日志写 stderr，stdout 只走 MCP 协议。
"""
import io
import json
import os
import shutil
import sys

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "envi-headless-bridge"
SERVER_VERSION = "0.2.0"
EXPECTED_TOKEN = os.environ.get("ENVI_BRIDGE_TOKEN", "").strip()

ENVI_DTYPES = {
    1: ("byte", 1), 2: ("int16", 2), 3: ("int32", 4), 4: ("float32", 4),
    5: ("float64", 8), 6: ("complex64", 8), 9: ("complex128", 16),
    12: ("uint16", 2), 13: ("uint32", 4), 14: ("int64", 8), 15: ("uint64", 8),
}
DATA_EXTS = (".dat", ".img", ".raw", ".bin", ".tif", ".tiff", "")


def log(*a):
    print("[envi-mcp]", *a, file=sys.stderr, flush=True)

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



# ==== HDR-SHARED-BEGIN ======================================================
# ENVI .hdr 解析的共享实现，与本包另一侧桥中的同名块保持逐字一致：
# 两侧运行形态不同（命令行脚本 / MCP 服务端），无法互相 import，
# 只能以内联副本同步维护。修改任一侧后必须同步另一侧。
def parse_hdr_text(text):
    """解析 .hdr 文本，返回 {key: value} 原始字典。

    .hdr 是 'key = value' 行集合（第一行通常是 'ENVI'），value 可以是
    {a, b, c} 形式且可跨多行；description 里也可能出现逗号与等号，
    因此按花括号深度逐字符切分，不能简单逐行 split。
    """
    body = text.strip()
    if body[:4].upper() == "ENVI":
        nl = body.find("\n")
        body = body[nl + 1:] if nl >= 0 else ""
    fields = {}
    i, n = 0, len(body)
    while i < n:
        # 扫描一个 key
        start = i
        while i < n and body[i] not in "=\n":
            i += 1
        if i >= n or body[i] != "=":
            break
        key = body[start:i].strip().lower()
        i += 1
        # 跳过等号后的空白
        while i < n and body[i] in " \t":
            i += 1
        if i < n and body[i] == "{":
            depth = 0
            vstart = i
            while i < n:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            raw = body[vstart:i]
        else:
            vstart = i
            while i < n and body[i] != "\n":
                i += 1
            raw = body[vstart:i].strip()
        if key:
            fields[key] = raw
        # 跳过行尾与空行
        while i < n and body[i] in "\r\n":
            i += 1
    return fields


def _brace_items(raw):
    """'{a, b, c}' -> ['a', 'b', 'c']；非花括号原样返回单元素列表。"""
    s = (raw or "").strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return [part.strip() for part in s.split(",") if part.strip() != ""]


def _to_int(v):
    try:
        return int(float(v))
    except Exception:
        return None


def _to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def hdr_summary(hdr_path):
    """读 .hdr 并生成结构化盘点条目；失败抛异常由调用方转结构化错误。"""
    with open(hdr_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if "samples" not in text.lower():
        raise ValueError("不是 ENVI .hdr 文件（缺少 samples 字段）: %s" % hdr_path)
    fields = parse_hdr_text(text)
    samples = _to_int(fields.get("samples"))
    lines = _to_int(fields.get("lines"))
    bands = _to_int(fields.get("bands"))
    dtype_code = _to_int(fields.get("data type"))
    dtype_name, dtype_bytes = ENVI_DTYPES.get(dtype_code, (None, None))
    wavelength = [_to_float(x) for x in _brace_items(fields.get("wavelength", ""))]
    entry = {
        "hdr": hdr_path,
        "description": (fields.get("description") or "").strip().strip("{}").strip() or None,
        "samples": samples,
        "lines": lines,
        "bands": bands,
        "data_type_code": dtype_code,
        "data_type": dtype_name,
        "interleave": (fields.get("interleave") or "").strip().lower() or None,
        "byte_order": _to_int(fields.get("byte order")),
        "header_offset": _to_int(fields.get("header offset")),
        "file_type": (fields.get("file type") or "").strip() or None,
        "sensor_type": (fields.get("sensor type") or "").strip() or None,
        "map_info": [x for x in _brace_items(fields.get("map info", ""))] or None,
        "band_names": _brace_items(fields.get("band names", "")) or None,
        "wavelength": wavelength or None,
        "wavelength_units": (fields.get("wavelength units") or "").strip() or None,
    }
    if None not in (samples, lines, bands) and dtype_bytes:
        entry["expected_data_bytes"] = samples * lines * bands * dtype_bytes
    else:
        entry["expected_data_bytes"] = None
    # 找同名数据文件并核对实际大小
    data_path = find_data_file(hdr_path)
    entry["data_file"] = data_path
    if data_path and os.path.isfile(data_path):
        entry["data_bytes"] = os.path.getsize(data_path)
        exp = entry["expected_data_bytes"]
        off = entry["header_offset"] or 0
        entry["size_matches"] = (exp is not None and entry["data_bytes"] == exp + off)
    else:
        entry["data_bytes"] = None
        entry["size_matches"] = None
    return entry


def find_data_file(hdr_path):
    """由 .hdr 路径找同名数据文件：依次试 .dat/.img/.raw/.bin/.tif/无扩展名。"""
    root, ext = os.path.splitext(hdr_path)
    if ext.lower() != ".hdr":
        root = hdr_path
    for cand_ext in DATA_EXTS:
        cand = root + cand_ext
        if os.path.isfile(cand) and cand != hdr_path:
            return cand
    return None


def find_hdr_file(data_path):
    root, _ext = os.path.splitext(data_path)
    for cand in (data_path + ".hdr", root + ".hdr"):
        if os.path.isfile(cand):
            return cand
    return None
# ==== HDR-SHARED-END ========================================================


# ------------------------------------------------------------- ENVI session
_SESSION = {"tried": False, "idl": None, "envi": None, "error": None}


def idlpy_importable():
    try:
        import idlpy  # noqa: F401
        return True, None
    except Exception as e:
        return False, str(e)


def get_envi_session():
    """惰性启动 HEADLESS ENVI 会话（只试一次，失败记因不重试）。"""
    if not _SESSION["tried"]:
        _SESSION["tried"] = True
        try:
            from idlpy import IDL
            _SESSION["idl"] = IDL
            _SESSION["envi"] = IDL.ENVI(HEADLESS=1)
        except Exception as e:
            _SESSION["error"] = str(e)
    return _SESSION["envi"], _SESSION["idl"], _SESSION["error"]


def install_hints():
    hints = {}
    for var in ("IDL_DIR", "EXELIS_DIR", "HARRIS_DIR", "NV5_DIR"):
        if os.environ.get(var):
            hints[var] = os.environ[var]
    for cand in (r"C:\Program Files\Harris", r"C:\Program Files\NV5",
                 r"C:\Program Files\Exelis", r"C:\Program Files\L3Harris",
                 "/usr/local/harris", "/usr/local/nv5", "/usr/local/exelis",
                 "/opt/harris", "/opt/nv5"):
        if os.path.isdir(cand):
            hints.setdefault("install_dirs", []).append(cand)
    for exe in ("idl", "envi"):
        found = shutil.which(exe)
        if found:
            hints.setdefault("on_path", []).append(found)
    return hints


def _task_names(envi, idl):
    """多策略抽样 ENVITask 任务名，与 probe_api.py 同口径。"""
    for attr in ("TASK_NAMES", "TaskNames", "TASKS", "Tasks"):
        try:
            val = getattr(envi, attr)
            if callable(val):
                val = val()
            names = [str(x) for x in list(val)]
            if names:
                return names, "envi.%s" % attr
        except Exception:
            continue
    for expr in ("ENVITaskNames()", "ENVITask(/LIST)"):
        try:
            val = idl(expr)
            names = [str(x) for x in list(val)]
            if names:
                return names, "IDL(%s)" % expr
        except Exception:
            continue
    return [], None


def _make_task(envi, idl, name, notes):
    """多策略构造 ENVITask 对象。"""
    for label, fn in (("envi.Task", lambda: envi.Task(name)),
                      ("IDL.ENVITask", lambda: idl.ENVITask(name))):
        try:
            task = fn()
            if task is not None:
                return task, label
        except Exception as e:
            notes.append("%s failed: %s" % (label, e))
    return None, None


def _get_attr(obj, names):
    for name in names:
        try:
            val = getattr(obj, name)
            if callable(val):
                val = val()
            return val, name
        except Exception:
            continue
    return None, None


# ------------------------------------------------------------------- tools
def tool_ping(args):
    ok, err = idlpy_importable()
    return {"ok": True, "pong": True, "bridge": SERVER_NAME,
            "version": SERVER_VERSION, "mode": "headless",
            "idlpy_importable": ok}


def tool_discover(args):
    ok, err = idlpy_importable()
    return {"ok": True, "mode": "headless",
            "note": "ENVI 无官方支持的 GUI 会话附着通道；本桥只有无头模式",
            "idlpy_importable": ok,
            "idlpy_error": err,
            "envi_available": ok,
            "session_started": _SESSION["envi"] is not None,
            "session_error": _SESSION["error"],
            "install_hints": install_hints(),
            "hdr_parser": "available (pure python)"}


def tool_raster_info(args):
    path = args.get("path")
    if not path:
        return {"ok": False, "error_code": "MISSING_ARGUMENT",
                "message": "缺少参数 path"}
    if not os.path.exists(path):
        return {"ok": False, "error_code": "FILE_NOT_FOUND",
                "message": "路径不存在: %s" % path}
    hdr = path if path.lower().endswith(".hdr") else find_hdr_file(path)
    result = {"ok": True, "path": path}
    if hdr and os.path.isfile(hdr):
        try:
            result["source"] = "hdr-parse"
            result["raster"] = hdr_summary(hdr)
        except Exception as e:
            return {"ok": False, "error_code": "HDR_PARSE_FAILED",
                    "message": str(e), "path": path}
    else:
        result["hdr"] = None
        result["note"] = "未找到 .hdr，尝试用 ENVI 打开核对"
    if args.get("verify"):
        envi, _idl, err = get_envi_session()
        if envi is None:
            if result.get("source") == "hdr-parse":
                result["envi_crosscheck"] = {"available": False, "error": err}
                return result
            return {"ok": False, "error_code": "ENVI_NOT_AVAILABLE",
                    "message": "无 .hdr 且 ENVI 会话不可用: %s" % err,
                    "path": path}
        try:
            raster, via = _get_attr(envi, ["OpenRaster"])
            open_fn = getattr(envi, "OpenRaster")
            raster = open_fn(path)
            info, _ = {}, None
            for key, names in (("ncolumns", ["NCOLUMNS", "NColumns"]),
                               ("nrows", ["NROWS", "NRows"]),
                               ("nbands", ["NBANDS", "NBands"]),
                               ("data_type", ["DATA_TYPE", "DataType"]),
                               ("interleave", ["INTERLEAVE", "Interleave"])):
                val, _via = _get_attr(raster, names)
                info[key] = val if isinstance(val, (int, float, str)) else str(val)
            result["source"] = "envi"
            result["envi"] = info
            try:
                raster.Close()
            except Exception:
                pass
        except Exception as e:
            if result.get("source") == "hdr-parse":
                result["envi_crosscheck"] = {"available": True, "error": str(e)}
                return result
            return {"ok": False, "error_code": "ENVI_OPEN_FAILED",
                    "message": str(e), "path": path}
    return result


def tool_list_tasks(args):
    envi, idl, err = get_envi_session()
    if envi is None:
        return {"ok": False, "error_code": "ENVI_NOT_AVAILABLE",
                "message": "ENVI 会话不可用，无法列任务: %s" % err}
    names, via = _task_names(envi, idl)
    if not names:
        return {"ok": False, "error_code": "TASK_LIST_UNAVAILABLE",
                "message": "已连上 ENVI 但任务名枚举策略全部失败；"
                           "可用 envi_describe_task 按已知任务名逐个查"}
    limit = args.get("limit") or 200
    return {"ok": True, "via": via, "count": len(names),
            "tasks": names[:int(limit)]}


def tool_describe_task(args):
    name = args.get("task")
    if not name:
        return {"ok": False, "error_code": "MISSING_ARGUMENT",
                "message": "缺少参数 task（ENVITask 名）"}
    envi, idl, err = get_envi_session()
    if envi is None:
        return {"ok": False, "error_code": "ENVI_NOT_AVAILABLE",
                "message": "ENVI 会话不可用，无法描述任务: %s" % err}
    notes = []
    task, via = _make_task(envi, idl, name, notes)
    if task is None:
        return {"ok": False, "error_code": "TASK_NOT_FOUND",
                "message": "构造 ENVITask 失败: %s" % name, "notes": notes}
    params = []
    for attr in dir(task):
        if attr.startswith("_") or not attr.upper() == attr:
            continue
        try:
            val = getattr(task, attr)
        except Exception:
            val = "<unreadable>"
        if callable(val):
            continue
        params.append({"name": attr,
                       "default": None if val is None else str(val)[:200]})
    meta = {}
    for key, names in (("name", ["NAME", "Name"]),
                       ("display_name", ["DISPLAY_NAME", "DisplayName"]),
                       ("description", ["DESCRIPTION", "Description"])):
        val, _v = _get_attr(task, names)
        meta[key] = None if val is None else str(val)[:500]
    return {"ok": True, "task": name, "via": via, "meta": meta,
            "parameters": sorted(params, key=lambda p: p["name"]),
            "notes": notes}


def tool_run_task(args):
    if args.get("confirm") is not True:
        return {"ok": False, "error_code": "CONFIRM_REQUIRED",
                "message": "run_task 是写类动作，必须带 confirm=true 才执行；"
                           "confirm 只能由用户明确同意后填入"}
    name = args.get("task")
    params = args.get("params") or {}
    if not name:
        return {"ok": False, "error_code": "MISSING_ARGUMENT",
                "message": "缺少参数 task（ENVITask 名）"}
    envi, idl, err = get_envi_session()
    if envi is None:
        return {"ok": False, "error_code": "ENVI_NOT_AVAILABLE",
                "message": "ENVI 会话不可用，未执行任何任务: %s" % err,
                "executed": False}
    notes = []
    task, via = _make_task(envi, idl, name, notes)
    if task is None:
        return {"ok": False, "error_code": "TASK_NOT_FOUND",
                "message": "构造 ENVITask 失败: %s" % name, "notes": notes,
                "executed": False}
    set_report = {}
    for key, value in params.items():
        applied = False
        for cand in (key, key.upper()):
            try:
                setattr(task, cand, value)
                set_report[key] = "set via %s" % cand
                applied = True
                break
            except Exception as e:
                set_report[key] = "failed: %s" % e
        if not applied:
            notes.append("param %s not applied" % key)
    try:
        execute = getattr(task, "Execute")
        execute()
    except Exception as e:
        return {"ok": False, "error_code": "TASK_RUN_FAILED",
                "message": "任务执行失败: %s" % e, "task": name, "via": via,
                "params_set": set_report, "notes": notes, "executed": False}
    outputs = {}
    for attr in dir(task):
        if attr.startswith("OUTPUT") and not attr.startswith("_"):
            try:
                val = getattr(task, attr)
                outputs[attr] = None if val is None else str(val)[:300]
            except Exception:
                pass
    return {"ok": True, "task": name, "via": via, "executed": True,
            "params_set": set_report, "outputs": outputs, "notes": notes}


def tool_export_raster_subset(args):
    if args.get("confirm") is not True:
        return {"ok": False, "error_code": "CONFIRM_REQUIRED",
                "message": "export 会生成新文件，必须带 confirm=true 才执行"}
    src = args.get("input")
    out = args.get("output")
    if not src or not out:
        return {"ok": False, "error_code": "MISSING_ARGUMENT",
                "message": "需要参数 input 与 output"}
    envi, idl, err = get_envi_session()
    if envi is None:
        return {"ok": False, "error_code": "NOT_SUPPORTED_IN_HDR_MODE",
                "message": "无 ENVI 会话时只有 .hdr 盘点能力，裁剪导出需要 "
                           "ENVITask/ENVIRaster，未执行: %s" % err,
                "executed": False}
    notes = []
    try:
        raster = getattr(envi, "OpenRaster")(src)
        subset = None
        for label, fn in (
            ("ENVIRaster.Subset",
             lambda: raster.Subset(SUB_RECT=[args.get("sub_rect")])),
        ):
            try:
                subset = fn()
                notes.append("subset via %s" % label)
                break
            except Exception as e:
                notes.append("%s failed: %s" % (label, e))
        if subset is None:
            return {"ok": False, "error_code": "SUBSET_FAILED",
                    "message": "裁剪策略失败", "notes": notes, "executed": False}
        subset.Export(out, "ENVI")
        landed = os.path.isfile(out) and os.path.getsize(out) > 0
        return {"ok": landed, "output": out, "executed": True,
                "bytes": os.path.getsize(out) if landed else 0,
                "notes": notes}
    except Exception as e:
        return {"ok": False, "error_code": "EXPORT_FAILED",
                "message": str(e), "notes": notes, "executed": False}


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}
_OBJ = {"type": "object"}

TOOL_DEFS = [
    ("envi_ping", "连通性检查：无头桥是否在线（顺带报 idlpy 是否可导入）", {},
     tool_ping),
    ("envi_discover", "发现本机 ENVI/idlpy 可用性与安装线索（校准用，只读）", {},
     tool_discover),
    ("envi_raster_info", "栅格盘点：优先纯 Python 解析 .hdr（source=hdr-parse）；"
     "传 verify=true 且 idlpy 可用时用 ENVI 打开核对（source=envi）",
     {"path": dict(_STR, description="栅格数据文件或 .hdr 路径（必填）"),
      "verify": dict(_BOOL, description="是否用 ENVI 打开核对（可选）")},
     tool_raster_info),
    ("envi_list_tasks", "列出 ENVITask 任务名抽样；无 ENVI 时结构化返回 ENVI_NOT_AVAILABLE",
     {"limit": dict(_INT, description="最多返回条数（可选，默认 200）")},
     tool_list_tasks),
    ("envi_describe_task", "描述某 ENVITask 的参数 schema（构造任务对象读参数，不执行）；"
     "无 ENVI 时结构化返回",
     {"task": dict(_STR, description="ENVITask 名（必填）")},
     tool_describe_task),
    ("envi_run_task", "【写】经 ENVITask 执行一个 ENVI 任务，须 confirm=true；"
     "无 ENVI 时返回 ENVI_NOT_AVAILABLE，绝不假装执行",
     {"task": dict(_STR, description="ENVITask 名（必填）"),
      "params": dict(_OBJ, description="任务参数 JSON 对象（可选）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")},
     tool_run_task),
    ("envi_export_raster_subset", "【写】导出栅格子集到新文件，须 confirm=true；"
     "仅 .hdr 模式下结构化报错 NOT_SUPPORTED_IN_HDR_MODE",
     {"input": dict(_STR, description="输入栅格路径（必填）"),
      "output": dict(_STR, description="输出栅格路径（必填）"),
      "sub_rect": dict(_OBJ, description="裁剪矩形 [x0,y0,x1,y1]（可选）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")},
     tool_export_raster_subset),
]

TOOL_FUNCS = {name: fn for name, _d, _p, fn in TOOL_DEFS}


def tools_list():
    return [{"name": name,
             "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props, _fn in TOOL_DEFS]


def _tool_result(result):
    text = json.dumps(_to_text(result), ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}],
            "isError": not result.get("ok", False)}


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
        args = params.get("arguments") or {}
        if EXPECTED_TOKEN:
            provided = ((params.get("_meta") or {}).get("token") or "")
            if provided != EXPECTED_TOKEN:
                return {"jsonrpc": "2.0", "id": mid,
                        "result": _tool_result({
                            "ok": False, "error_code": "BAD_TOKEN",
                            "message": "token 缺失或不正确，拒绝执行"})}
        fn = TOOL_FUNCS.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": "unknown tool: %s" % name}],
                "isError": True}}
        try:
            return {"jsonrpc": "2.0", "id": mid, "result": _tool_result(fn(args))}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": _tool_result({
                "ok": False, "error_code": "TOOL_FAILED",
                "message": "%s 执行异常: %s" % (name, e)})}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    _lock_stdio_utf8()
    log("starting headless MCP; token gate=%s" % bool(EXPECTED_TOKEN))
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
