# -*- coding: utf-8 -*-
"""
mcp_server.py — GRASS GIS 无头桥 MCP 服务端（stdio，纯标准库，v0.1）

定位：GRASS GIS 没有“附着到已打开 GUI 会话”的官方通道，本包
只有无头批处理形态：以 grass <mapset> --exec <模块> 的方式在
本机跑 GRASS。它不是 GRASS GIS 官方组件，与 GRASS GIS / OSGeo
官方项目无隶属关系。

工具（7 个）：
  只读：grass_ping / grass_discover / grass_location_info /
        grass_list_maps / grass_raster_info
  写/执行类（须 confirm=true）：
        grass_run_module     只许三个固定作业模板
                             （slope_aspect / hillshade /
                             resample_nearest）；绝不传
                             --overwrite，输出只能是新图层
        grass_export_vector  v.out.ogr 把矢量图层导出为
                             GeoJSON 新文件；已存在的文件拒绝
没有 GRASS 的机器上，工具如实返回结构化 GRASS_NOT_AVAILABLE，
绝不假装执行过。没有任意模块执行工具：模块名与参数名都在
scripts/grass_bridge.py 里写死，调用方只能提供经校验的值。

token 守卫（常开，与本合集消费桥同口径）：每次 tools/call 须
在参数里带 _token 且与 GRASS_BRIDGE_TOKEN 环境变量、或 token
文件 ~/.grass-agent-bridge.token 的内容一致，否则以 BAD_TOKEN
拒绝。两者都未配置时，服务端启动即生成随机 token 写入该文件
（权限 0600）。本服务端走 stdio，不监听任何网络端口。

环境变量：
  GRASS_BRIDGE_TOKEN    token（优先于 token 文件）
  GRASS_BRIDGE_BIN      grass 可执行文件路径（默认走 PATH）
  GRASS_BRIDGE_GISDBASE GRASS 数据库根目录（业务工具必填；
                        location/mapset 只能是其下的单个分量名）
  GRASS_BRIDGE_EXPORT_DIR 导出根目录（可选，设置后导出只能
                        落在其中）
每次写/执行类调用都会往 ~/.grass-agent-bridge/runs.jsonl
追加一条记录（工具名、作业、状态、耗时）。日志写 stderr，
stdout 只走 MCP 协议。

证据口径：本包未经实机校准（开发机无 GRASS GIS 环境），只通过
协议级自检（live/selftest.py，含假 grass 替身）；不要把自检
通过当作已在真实 GRASS 上验证。实机校准工单见
docs/CALIBRATION.md。
"""
import io
import json
import os
import secrets
import sys
import time
from datetime import datetime

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "grass-headless-bridge"
SERVER_VERSION = "0.1.0"
TOKEN_FILE = os.path.join(os.path.expanduser("~"),
                          ".grass-agent-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"), ".grass-agent-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "runs.jsonl")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))

import grass_bridge as gb  # noqa: E402


def log(*a):
    print("[grass-mcp]", *a, file=sys.stderr, flush=True)


# ---- 序列化净化（与仓内各包同口径） ----
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
    """递归净化待 JSON 序列化的对象，保证 dumps 不会因异类对象崩溃。"""
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
    """把 stdin/stdout 锁定为 UTF-8；只在 main() 调用一次。"""
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


# ------------------------------------------------------------------ token
def expected_token():
    tok = os.environ.get("GRASS_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def ensure_token():
    """token 守卫常开：无任何配置时生成随机 token 写入文件（0600）。"""
    if expected_token():
        return
    tok = secrets.token_hex(16)
    try:
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tok)
        log("generated bridge token at %s (0600)" % TOKEN_FILE)
    except Exception as e:
        log("WARNING: cannot write token file %s: %s" % (TOKEN_FILE, e))


def journal(entry):
    try:
        os.makedirs(JOURNAL_DIR, exist_ok=True)
        entry = dict(entry)
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _err(e):
    return {"ok": False, "error_code": e.error_code, "message": e.message}


def _need_grass():
    if not gb.grass_available():
        return {"ok": False, "error_code": "GRASS_NOT_AVAILABLE",
                "message": "找不到 grass 可执行文件（%s）：请安装 "
                           "GRASS GIS，或用 GRASS_BRIDGE_BIN 指定路径"
                           % gb.grass_path()}
    return None


# ------------------------------------------------------------------ tools
def tool_ping(args):
    return {"ok": True, "pong": True, "bridge": SERVER_NAME,
            "version": SERVER_VERSION, "mode": "headless",
            "grass_available": gb.grass_available(),
            "grass_version": gb.grass_version()}


def tool_discover(args):
    return {"ok": True, "mode": "headless",
            "note": "GRASS GIS 无官方支持的 GUI 会话附着通道；"
                    "本桥只有无头批处理（--exec）模式",
            "grass": gb.grass_path(),
            "grass_available": gb.grass_available(),
            "grass_version": gb.grass_version(),
            "gisdbase": gb.gisdbase(),
            "gisdbase_configured": gb.gisdbase() is not None,
            "locations": gb.list_locations(),
            "run_jobs": sorted(gb.RUN_JOBS),
            "token_guard": "on",
            "journal_file": JOURNAL_FILE,
            "calibration": "未实机校准（协议自检级）；见 docs/CALIBRATION.md"}


def tool_location_info(args):
    try:
        info = gb.location_info(args.get("location"))
    except gb.BridgeError as e:
        return _err(e)
    info = dict(info)
    info["ok"] = True
    return info


def tool_list_maps(args):
    err = _need_grass()
    if err:
        return err
    map_type = args.get("type") or "raster"
    if map_type not in gb.MAP_TYPES:
        return {"ok": False, "error_code": "BAD_TYPE",
                "message": "type 只许 %s，收到 %r"
                           % (" / ".join(gb.MAP_TYPES), map_type)}
    try:
        mapset_path = gb.mapset_dir(args.get("location"),
                                    args.get("mapset"))
        out = gb.run_grass(mapset_path, ["g.list", "type=%s" % map_type])
    except gb.BridgeError as e:
        return _err(e)
    names = gb.parse_name_list(out)
    return {"ok": True, "location": args.get("location"),
            "mapset": args.get("mapset"), "type": map_type,
            "count": len(names), "maps": names}


def tool_raster_info(args):
    err = _need_grass()
    if err:
        return err
    try:
        gb.validate_map_name(args.get("map"))
        mapset_path = gb.mapset_dir(args.get("location"),
                                    args.get("mapset"))
        out = gb.run_grass(mapset_path,
                           ["r.info", "-g", "map=%s" % args.get("map")])
    except gb.BridgeError as e:
        return _err(e)
    return {"ok": True, "location": args.get("location"),
            "mapset": args.get("mapset"), "map": args.get("map"),
            "info": gb.parse_key_values(out)}


def tool_run_module(args):
    if args.get("confirm") is not True:
        return {"ok": False, "error_code": "CONFIRM_REQUIRED",
                "message": "run_module 是执行类动作，必须带 "
                           "confirm=true 才执行；confirm 只能由用户"
                           "明确同意后填入"}
    err = _need_grass()
    if err:
        return err
    t0 = time.time()
    try:
        module, argv, used = gb.build_run_args(args.get("job"),
                                               args.get("params") or {})
        mapset_path = gb.mapset_dir(args.get("location"),
                                    args.get("mapset"))
        out = gb.run_grass(mapset_path, argv)
    except gb.BridgeError as e:
        journal({"tool": "run_module", "job": args.get("job"),
                 "status": "error", "error_code": e.error_code})
        return _err(e)
    duration = round(time.time() - t0, 3)
    journal({"tool": "run_module", "job": args.get("job"),
             "status": "ok", "duration_s": duration})
    return {"ok": True, "job": args.get("job"), "module": module,
            "executed": True, "params": used,
            "location": args.get("location"),
            "mapset": args.get("mapset"),
            "overwrite_used": False,
            "grass_output_tail": out.strip()[-300:],
            "duration_s": duration}


def tool_export_vector(args):
    if args.get("confirm") is not True:
        return {"ok": False, "error_code": "CONFIRM_REQUIRED",
                "message": "export 会生成新文件，必须带 confirm=true "
                           "才执行；confirm 只能由用户明确同意后填入"}
    err = _need_grass()
    if err:
        return err
    t0 = time.time()
    try:
        gb.validate_map_name(args.get("map"))
        path = gb.resolve_export_path(args.get("output"))
        mapset_path = gb.mapset_dir(args.get("location"),
                                    args.get("mapset"))
        gb.run_grass(mapset_path,
                     ["v.out.ogr", "input=%s" % args.get("map"),
                      "output=%s" % path, "format=GeoJSON"])
    except gb.BridgeError as e:
        journal({"tool": "export_vector", "status": "error",
                 "error_code": e.error_code})
        return _err(e)
    landed = os.path.isfile(path) and os.path.getsize(path) > 0
    duration = round(time.time() - t0, 3)
    journal({"tool": "export_vector", "status": "ok" if landed else "error",
             "duration_s": duration})
    if not landed:
        return {"ok": False, "error_code": "EXPORT_NOT_LANDED",
                "message": "grass 已返回成功，但导出文件未落盘或为空：%s"
                           % path, "executed": True}
    return {"ok": True, "map": args.get("map"), "path": path,
            "bytes": os.path.getsize(path), "executed": True,
            "duration_s": duration,
            "next_step": "可用本仓 qgis/ 桥的 qgis_add_layer_from_path "
                         "把该文件加载进 QGIS（其校准状态见 qgis 包 README）"}


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_OBJ = {"type": "object"}

_LOC_PROP = dict(_STR, description="location 名（必填）：GRASS_BRIDGE_GISDBASE "
                 "下的单个目录名")
_MAPSET_PROP = dict(_STR, description="mapset 名（必填）：location 下的"
                    "单个目录名")
_MAP_PROP = dict(_STR, description="图层名（必填）：name 或 name@mapset，"
                 "只许 [A-Za-z0-9_.]")
_CONFIRM_PROP = dict(_BOOL, description="必须为 true 才执行")

TOOL_DEFS = [
    ("grass_ping", "连通性检查：无头桥是否在线，并回报 grass 是否可用与版本", {}),
    ("grass_discover", "环境发现：grass 可用性与版本、GIS 数据库根目录与其中 location 清单、可跑的固定作业枚举（校准用）", {}),
    ("grass_location_info", "读一个 location 的投影信息与默认区域（纯 Python 解析 PERMANENT/PROJ_INFO 与 WIND，不启动 GRASS）",
     {"location": _LOC_PROP}),
    ("grass_list_maps", "用固定 g.list 模板列某 mapset 里的图层名（type 只许 raster/vector/raster_3d/region）",
     {"location": _LOC_PROP, "mapset": _MAPSET_PROP,
      "type": dict(_STR, description="图层类型（可选，默认 raster）")}),
    ("grass_raster_info", "用固定 r.info -g 模板取一张栅格的范围/分辨率/行列数等键值信息",
     {"location": _LOC_PROP, "mapset": _MAPSET_PROP, "map": _MAP_PROP}),
    ("grass_run_module", "【执行】按固定作业模板跑一个 GRASS 处理作业（slope_aspect / hillshade / resample_nearest），须 confirm=true；绝不传 --overwrite，输出只能是新图层",
     {"location": _LOC_PROP, "mapset": _MAPSET_PROP,
      "job": dict(_STR, description="作业名（必填）：slope_aspect / hillshade / resample_nearest"),
      "params": dict(_OBJ, description="作业参数 JSON 对象：输入图层名与输出新图层名，按作业模板校验"),
      "confirm": _CONFIRM_PROP}),
    ("grass_export_vector", "【写】用固定 v.out.ogr 模板把一张矢量图层导出为 GeoJSON 新文件，须 confirm=true；文件已存在拒绝覆盖",
     {"location": _LOC_PROP, "mapset": _MAPSET_PROP, "map": _MAP_PROP,
      "output": dict(_STR, description="导出文件路径（必填，须 .geojson 且不得已存在）"),
      "confirm": _CONFIRM_PROP}),
]

HANDLERS = {
    "grass_ping": tool_ping,
    "grass_discover": tool_discover,
    "grass_location_info": tool_location_info,
    "grass_list_maps": tool_list_maps,
    "grass_raster_info": tool_raster_info,
    "grass_run_module": tool_run_module,
    "grass_export_vector": tool_export_vector,
}


def tools_list():
    out = []
    for name, desc, props in TOOL_DEFS:
        out.append({"name": name, "description": desc,
                    "inputSchema": {"type": "object",
                                    "properties": props}})
    return out


def _bad_token_reply(mid):
    payload = {"ok": False, "error_code": "BAD_TOKEN",
               "message": "token 缺失或不正确"}
    return {"jsonrpc": "2.0", "id": mid, "result": {
        "content": [{"type": "text",
                     "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": True}}


def _call_tool(mid, params):
    name = params.get("name")
    args = dict(params.get("arguments") or {})
    supplied = args.pop("_token", None)
    expect = expected_token()
    if not expect or supplied != expect:
        return _bad_token_reply(mid)
    handler = HANDLERS.get(name)
    if handler is None:
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text",
                         "text": "unknown tool: %s" % name}],
            "isError": True}}
    try:
        result = handler(args)
        text = json.dumps(_to_text(result), ensure_ascii=False, indent=2)
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": text}],
            "isError": False}}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text",
                         "text": "tool failed: %s" % e}],
            "isError": True}}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME,
                           "version": SERVER_VERSION}}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"tools": tools_list()}}
    if method == "tools/call":
        return _call_tool(mid, msg.get("params") or {})
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601,
                      "message": "method not found: %s" % method}}


def main():
    _lock_stdio_utf8()
    ensure_token()
    log("starting headless MCP; grass=%s gisdbase=%s token_guard=on" % (
        gb.grass_path(), gb.gisdbase() or "(not configured)"))
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
            sys.stdout.write(json.dumps(_to_text(resp),
                                        ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
