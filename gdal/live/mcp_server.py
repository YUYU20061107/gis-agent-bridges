# -*- coding: utf-8 -*-
"""
mcp_server.py — GDAL/OGR 工具桥 stdio MCP 服务端（纯 Python 标准库）

以固定模板调用本机 GDAL 命令行四件套（gdalinfo / ogrinfo /
gdal_translate / ogr2ogr），让 AI Agent 探查栅格与矢量文件、
取波段统计，并在用户确认后把文件转换成新文件。没有原始
GDAL 选项透传：没有 -co、没有任意参数拼接；输入只许本地
文件；所有子进程强制 GDAL_PAM_ENABLED=NO，只读探查不在
原件旁产生 .aux.xml；转换只写不存在的新文件，绝不覆盖。

token 守卫：本文件实现 token 守卫。服务端按以下顺序确定
期望 token：
  1) 环境变量 GDAL_BRIDGE_TOKEN（若设置则优先且固定）；
  2) token 文件（Linux/macOS ~/.gdal-agent-bridge.token；
     Windows %USERPROFILE%\\.gdal-agent-bridge.token）。
若两者都不存在，启动时生成随机 token 写入 token 文件
（尽量 0600）。之后每次 tools/call 都必须在 arguments 里
带 _token 且完全一致才执行，否则返回 BAD_TOKEN。

运行日志：转换类调用追加写入 ~/.gdal-agent-bridge/runs.jsonl
（含工具名、输入输出路径、状态，不含 token）。

运行（一般由 MCP 客户端拉起）：
    python3 live/mcp_server.py
stdout 是 MCP 协议通道，运行日志只写 stderr。
"""
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
import gdal_bridge as gb  # noqa: E402

SERVER_NAME = "gdal-tool-bridge"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

TOKEN_FILE_NAME = ".gdal-agent-bridge.token"


def _log(msg):
    sys.stderr.write("[%s] %s\n" % (SERVER_NAME, msg))
    sys.stderr.flush()


def _app_dir():
    return os.path.join(os.path.expanduser("~"), gb.APP_DIRNAME)


def _journal(entry):
    try:
        os.makedirs(_app_dir(), exist_ok=True)
        path = os.path.join(_app_dir(), "runs.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_expected_token():
    env_tok = os.environ.get("GDAL_BRIDGE_TOKEN")
    if env_tok:
        return env_tok
    path = os.path.join(os.path.expanduser("~"), TOKEN_FILE_NAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    except Exception:
        pass
    tok = secrets.token_hex(16)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(tok + "\n")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        _log("已生成新 token 并写入 %s" % path)
    except Exception as e:
        _log("token 文件写入失败，本次会话内存 token：%s" % e)
    return tok


EXPECTED_TOKEN = _load_expected_token()


def _check_token(args):
    tok = args.get("_token")
    return isinstance(tok, str) and secrets.compare_digest(tok, EXPECTED_TOKEN)


def _err(code, message):
    return {"ok": False, "error_code": code, "message": message}


def _require_confirm(args, action):
    if args.get("confirm") is not True:
        raise gb.BridgeError(
            "CONFIRM_REQUIRED",
            "%s 是写类动作，必须带 confirm=true 才执行；confirm 只能由"
            "用户明确同意后填入" % action)


# ---------------------------------------------------------------- 工具

def tool_ping(args):
    info = versions()
    return {"ok": True, "pong": True, "bridge": SERVER_NAME,
            "version": SERVER_VERSION, "mode": "headless-tools",
            "gdalinfo_available": info["gdalinfo"]["available"],
            "ogrinfo_available": info["ogrinfo"]["available"],
            "any_tool_available": any(v["available"] for v in info.values())}


def versions():
    out = {}
    for key, path, label in (
            ("gdalinfo", gb.gdalinfo_path(), "gdalinfo"),
            ("ogrinfo", gb.ogrinfo_path(), "ogrinfo"),
            ("gdal_translate", gb.gdal_translate_path(), "gdal_translate"),
            ("ogr2ogr", gb.ogr2ogr_path(), "ogr2ogr")):
        out[key] = {"path": path, "available": gb.tool_available(path),
                    "version": gb.tool_version(path, label)
                    if gb.tool_available(path) else None}
    return out


def tool_discover(args):
    return {
        "ok": True,
        "mode": "headless-tools",
        "note": "本桥以固定模板调用 GDAL 命令行工具，不接收任何原始 "
                "GDAL 选项串；所有子进程强制 GDAL_PAM_ENABLED=NO，"
                "只读探查不在原件旁产生 .aux.xml",
        "tools": versions(),
        "raster_formats": gb.RASTER_FORMATS,
        "vector_formats": gb.VECTOR_FORMATS,
        "timeout_s": gb.timeout_s(),
        "input_policy": "只许本地已存在文件；远程与 /vsi 路径一律拒绝",
        "output_policy": "转换只写尚不存在的新文件，扩展名须与格式匹配",
        "next_step": "先用 gdal_raster_info / gdal_vector_info 看清输入"
                     "文件，再谈转换",
    }


def tool_raster_info(args):
    path = gb.validate_input_path(args.get("path"))
    return dict({"ok": True}, **gb.raster_info(path))


def tool_vector_info(args):
    path = gb.validate_input_path(args.get("path"))
    return dict({"ok": True}, **gb.vector_info(path))


def tool_raster_stats(args):
    path = gb.validate_input_path(args.get("path"))
    return dict({"ok": True}, **gb.raster_stats(path))


def tool_convert_raster(args):
    _require_confirm(args, "convert_raster")
    started = time.time()
    entry = {"ts": datetime.now(timezone.utc).isoformat(),
             "tool": "gdal_convert_raster", "executed": False}
    try:
        result = gb.convert_raster(args.get("path"), args.get("output"),
                                   args.get("format"))
        entry.update({"executed": True,
                      "duration_s": round(time.time() - started, 3),
                      "input": result["input"],
                      "output": result["output"]})
        return result
    except gb.BridgeError as e:
        entry.update({"error_code": e.error_code})
        raise
    finally:
        _journal(entry)


def tool_convert_vector(args):
    _require_confirm(args, "convert_vector")
    started = time.time()
    entry = {"ts": datetime.now(timezone.utc).isoformat(),
             "tool": "gdal_convert_vector", "executed": False}
    try:
        result = gb.convert_vector(args.get("path"), args.get("output"),
                                   args.get("format"))
        entry.update({"executed": True,
                      "duration_s": round(time.time() - started, 3),
                      "input": result["input"],
                      "output": result["output"]})
        return result
    except gb.BridgeError as e:
        entry.update({"error_code": e.error_code})
        raise
    finally:
        _journal(entry)


TOOLS = [
    {
        "name": "gdal_ping",
        "description": "连通性检查：桥版本、gdalinfo/ogrinfo 是否可用。",
        "inputSchema": {"type": "object", "properties": {
            "_token": {"type": "string"}}},
    },
    {
        "name": "gdal_discover",
        "description": "环境发现（校准用）：四件工具的路径/可用性/版本、"
                       "可转换格式枚举、输入输出政策口径。",
        "inputSchema": {"type": "object", "properties": {
            "_token": {"type": "string"}}},
    },
    {
        "name": "gdal_raster_info",
        "description": "【只读】gdalinfo -json 探查栅格：驱动、尺寸、"
                       "波段数、仿射变换、角点坐标、投影（截断回传）。"
                       "强制 PAM 关闭，不在原件旁写 .aux.xml。",
        "inputSchema": {"type": "object", "properties": {
            "_token": {"type": "string"},
            "path": {"type": "string", "description": "本地栅格文件路径"}},
            "required": ["path"]},
    },
    {
        "name": "gdal_vector_info",
        "description": "【只读】ogrinfo -so -al 探查矢量：图层名、几何"
                       "类型、要素数、范围、字段名清单。",
        "inputSchema": {"type": "object", "properties": {
            "_token": {"type": "string"},
            "path": {"type": "string", "description": "本地矢量文件路径"}},
            "required": ["path"]},
    },
    {
        "name": "gdal_raster_stats",
        "description": "【只读】gdalinfo -stats -json 取各波段 "
                       "min/max/mean/stdDev。经 GDAL_PAM_ENABLED=NO "
                       "计算，不在原件旁产生 .aux.xml。",
        "inputSchema": {"type": "object", "properties": {
            "_token": {"type": "string"},
            "path": {"type": "string", "description": "本地栅格文件路径"}},
            "required": ["path"]},
    },
    {
        "name": "gdal_convert_raster",
        "description": "【写，须 confirm=true】用 gdal_translate 把栅格"
                       "转成新文件。format 只许 GTiff/PNG/JPEG（固定 "
                       "-of 模板，无任意选项透传）；输出必须尚不存在、"
                       "扩展名与格式匹配；绝不覆盖已有文件。",
        "inputSchema": {"type": "object", "properties": {
            "_token": {"type": "string"},
            "path": {"type": "string", "description": "输入栅格路径"},
            "output": {"type": "string",
                       "description": "输出新文件路径（须不存在）"},
            "format": {"type": "string", "enum": ["GTiff", "PNG", "JPEG"]},
            "confirm": {"type": "boolean",
                        "description": "用户明确同意后才可为 true"}},
            "required": ["path", "output", "format", "confirm"]},
    },
    {
        "name": "gdal_convert_vector",
        "description": "【写，须 confirm=true】用 ogr2ogr 把矢量转成新"
                       "文件/数据集。format 只许 GeoJSON/GPKG（固定 -f "
                       "模板）；输出必须尚不存在、扩展名与格式匹配；"
                       "绝不覆盖已有文件。",
        "inputSchema": {"type": "object", "properties": {
            "_token": {"type": "string"},
            "path": {"type": "string", "description": "输入矢量路径"},
            "output": {"type": "string",
                       "description": "输出新文件路径（须不存在）"},
            "format": {"type": "string", "enum": ["GeoJSON", "GPKG"]},
            "confirm": {"type": "boolean",
                        "description": "用户明确同意后才可为 true"}},
            "required": ["path", "output", "format", "confirm"]},
    },
]

HANDLERS = {
    "gdal_ping": tool_ping,
    "gdal_discover": tool_discover,
    "gdal_raster_info": tool_raster_info,
    "gdal_vector_info": tool_vector_info,
    "gdal_raster_stats": tool_raster_stats,
    "gdal_convert_raster": tool_convert_raster,
    "gdal_convert_vector": tool_convert_vector,
}


def _text_result(obj, is_error=False):
    return {"content": [{"type": "text",
                         "text": json.dumps(obj, ensure_ascii=False)}],
            "isError": is_error}


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
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": mid, "result": _text_result(
                _err("UNKNOWN_TOOL", "未知工具：%s" % name), True)}
        if not _check_token(args):
            return {"jsonrpc": "2.0", "id": mid, "result": _text_result(
                _err("BAD_TOKEN", "token 缺失或不正确"), True)}
        try:
            result = handler(args)
            return {"jsonrpc": "2.0", "id": mid,
                    "result": _text_result(result)}
        except gb.BridgeError as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": _text_result(e.to_dict(), True)}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": _text_result(
                _err("INTERNAL", "内部错误：%s" % e), True)}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "未知方法：%s" % method}}


def main():
    _log("已启动（stdio）。token 来源：%s；GDAL_PAM_ENABLED 对子进程"
         "强制为 NO"
         % ("环境变量 GDAL_BRIDGE_TOKEN" if os.environ.get("GDAL_BRIDGE_TOKEN")
            else "token 文件 ~/.gdal-agent-bridge.token"))
    inp = sys.stdin.buffer
    out = sys.stdout.buffer
    while True:
        line = inp.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            out.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()


if __name__ == "__main__":
    main()
