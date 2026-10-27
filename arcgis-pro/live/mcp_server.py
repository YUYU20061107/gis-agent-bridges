# -*- coding: utf-8 -*-
"""
mcp_server.py — MCP 服务端（stdio，纯标准库，v0.2）

把 MCP 工具调用转发到 ArcGIS Pro 内的应用内桥（inapp_bridge.py，127.0.0.1:47616）。
把本服务端注册到你的 AI Agent / MCP 客户端的 MCP 配置后，Agent 即可用下列工具
操作 ArcGIS Pro 当前打开的工程：
  只读：arcgis_ping / arcgis_discover / arcgis_project_info / arcgis_list_maps /
        arcgis_list_layers / arcgis_list_tables / arcgis_list_layouts /
        arcgis_export_map_image
  视图级（只改显示、可逆）：arcgis_set_layer_visible / arcgis_zoom_to_layer /
        arcgis_set_labels_visible
  写类（须 confirm=true）：arcgis_add_layer_from_path / arcgis_save_project
工具面刻意收窄：不提供任意代码执行、任意 GP 工具调用类工具（有意的安全取舍）。
v0.2 的实时桥为实验性实现，未在真实 ArcGIS Pro 上验证；桥侧调不通时会返回
结构化错误，Agent 必须如实回报，不许把错误说成成功。

环境变量：
  ARCPRO_BRIDGE_HOST（默认 127.0.0.1）、ARCPRO_BRIDGE_PORT（默认 47616）、
  ARCPRO_BRIDGE_TOKEN（优先；否则读 ARCGIS_PRO_BRIDGE_TOKEN_FILE 指定的 token 文件，
  默认 ~/.arcgis-pro-live-bridge.token）
日志写 stderr，stdout 只走 MCP 协议。
"""
import io
import json
import os
import socket
import sys

HOST = os.environ.get("ARCPRO_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ARCPRO_BRIDGE_PORT", "47616"))
TOKEN_FILE = os.environ.get("ARCGIS_PRO_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".arcgis-pro-live-bridge.token")
PROTOCOL_VERSION = "2024-11-05"


def log(*a):
    print("[arcgis-pro-mcp]", *a, file=sys.stderr, flush=True)

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



def get_token():
    tok = os.environ.get("ARCPRO_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


# 连接与读写分开计时：连接失败几乎总是「桥没起」，而读超时几乎总是
# 「ArcGIS Pro 主线程被模态对话框/长地理处理占住」。合成一个 30s 总超时会
# 让 Agent 无法区分这两种可恢复性完全不同的故障。
CONNECT_TIMEOUT = float(os.environ.get("ARCPRO_BRIDGE_CONNECT_TIMEOUT", "5"))
IO_TIMEOUT = float(os.environ.get("ARCPRO_BRIDGE_IO_TIMEOUT", "120"))


class BridgeError(Exception):
    """带错误码的桥调用失败，用于给客户端结构化回报（无头桥同口径）。"""

    def __init__(self, code, message, hint=None, detail=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.hint = hint
        self.detail = detail

    def as_dict(self, tool):
        d = {"ok": False, "error_code": self.code, "message": self.message,
             "tool": tool, "bridge": "%s:%d" % (HOST, PORT)}
        if self.hint:
            d["hint"] = self.hint
        if self.detail:
            d["detail"] = self.detail
        return d


def call_bridge(tool, args):
    payload = {"token": get_token(), "tool": tool, "args": args or {}}
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        sock = socket.create_connection((HOST, PORT), timeout=CONNECT_TIMEOUT)
    except socket.timeout:
        raise BridgeError(
            "BRIDGE_TIMEOUT",
            "连接 %s:%d 超时（%.1fs）" % (HOST, PORT, CONNECT_TIMEOUT),
            hint="桥未监听，或 ArcGIS Pro 主线程被对话框/长任务阻塞；确认 ArcGIS Pro 已打开且 "
                 "inapp_bridge.py 已在其中的 Python 窗口运行")
    except OSError as e:
        raise BridgeError(
            "BRIDGE_UNREACHABLE",
            "无法连接 %s:%d：%s" % (HOST, PORT, e),
            hint="核对 ARCPRO_BRIDGE_PORT 是否与桥一致、桥进程是否存活、本机回环是否被拦截")
    buf = b""
    try:
        with sock:
            sock.settimeout(IO_TIMEOUT)
            sock.sendall(data)
            while b"\n" not in buf:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    raise BridgeError(
                        "BRIDGE_TIMEOUT",
                        "等待桥响应超过 %.0fs（已收到 %d 字节）" % (IO_TIMEOUT, len(buf)),
                        hint="ArcGIS Pro 可能正被模态对话框或长地理处理占用；先处理界面再重试，"
                             "不要连环重试")
                if not chunk:
                    break
                buf += chunk
    except BridgeError:
        raise
    except OSError as e:
        raise BridgeError("BRIDGE_IO_ERROR", "与桥通信失败：%s" % e,
                          hint="桥进程可能中途退出；确认 ArcGIS Pro 仍在运行后重试")
    if not buf.strip():
        raise BridgeError("BRIDGE_NO_RESPONSE",
                          "桥关闭了连接但没有返回任何数据",
                          hint="桥脚本可能异常退出，检查 ArcGIS Pro 的 Python 窗口输出")
    try:
        resp = json.loads(buf.decode("utf-8"))
    except Exception as e:
        raise BridgeError("BRIDGE_PROTOCOL", "桥返回的不是合法 JSON：%s" % e,
                          detail=_dec(buf[:400]))
    if not isinstance(resp, dict):
        raise BridgeError("BRIDGE_PROTOCOL", "桥返回的 JSON 顶层不是对象", detail=_dec(buf[:400]))
    if not resp.get("ok"):
        raise BridgeError("BRIDGE_ERROR", resp.get("error", "bridge error"),
                          hint="这是桥业务层的拒绝/失败（如 BAD_TOKEN、参数不合法），"
                               "按 error 文本处置，不要把失败当成功回报")
    return resp.get("result")


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}

TOOL_DEFS = [
    ("arcgis_ping", "连通性检查：桥是否在线", {}),
    ("arcgis_discover", "发现 ArcGIS Pro 当前工程的接入方式并回报现场 API 信息（校准用）", {}),
    ("arcgis_project_info", "当前工程概览：文件路径、默认地理数据库、地图数/布局数、接入模式", {}),
    ("arcgis_list_maps", "列出当前工程的全部地图（名称、类型）", {}),
    ("arcgis_list_layers", "列出某地图的图层（下标、名称、显隐、数据源、是否断裂）；map 省略时取第一幅地图",
     {"map": dict(_STR, description="地图名（可选）")}),
    ("arcgis_list_tables", "列出某地图的独立表（名称、数据源、是否断裂）；map 省略时取第一幅地图",
     {"map": dict(_STR, description="地图名（可选）")}),
    ("arcgis_list_layouts", "列出当前工程的全部布局（名称、页面宽高、地图框数）", {}),
    ("arcgis_set_layer_visible", "【视图级·实验性】设置图层显隐，只改显示状态、可逆",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示，false=隐藏")}),
    ("arcgis_zoom_to_layer", "【视图级·实验性】把活动视图缩放到图层范围；做不到会报 NOT_SUPPORTED",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）")}),
    ("arcgis_set_labels_visible", "【视图级·实验性】开关图层标注显示，只改显示状态、可逆",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示标注，false=关闭标注")}),
    ("arcgis_add_layer_from_path", "【写·实验性】把数据路径（要素类/shp/栅格等）加入地图，须 confirm=true；调不通会如实报错",
     {"map": dict(_STR, description="地图名（可选，省略取第一幅）"),
      "path": dict(_STR, description="数据路径（必填）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("arcgis_export_map_image", "【实验性】把布局（或其地图框）导出为 PNG 到指定路径，以文件真实落盘为准",
     {"layout": dict(_STR, description="布局名（可选；工程内只有一个布局时可省略）"),
      "map": dict(_STR, description="地图名（可选）"),
      "out_path": dict(_STR, description="PNG 输出路径（必填，目录须已存在）"),
      "resolution": dict(_INT, description="导出分辨率 DPI（可选，默认 200）"),
      "width": dict(_INT, description="宽度像素（可选，地图框导出变体用）"),
      "height": dict(_INT, description="高度像素（可选，地图框导出变体用）")}),
    ("arcgis_save_project", "保存当前工程（写操作，必须 confirm=true）",
     {"confirm": dict(_BOOL, description="必须为 true 才执行")}),
]

BRIDGE_TOOL = {name: name.replace("arcgis_", "", 1) for name, _, _ in TOOL_DEFS}


def tools_list():
    return [{"name": name,
             "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props in TOOL_DEFS]


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "arcgis-pro-live-bridge", "version": "0.2.0"}}}
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
        if name not in BRIDGE_TOOL:
            err = {"ok": False, "error_code": "UNKNOWN_TOOL",
                   "message": "unknown tool: %s" % name,
                   "available": sorted(BRIDGE_TOOL.keys())}
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(err, ensure_ascii=False, indent=2)}],
                "isError": True, "structuredContent": err}}
        try:
            result = call_bridge(BRIDGE_TOOL[name], args)
            text = json.dumps(_to_text(result), ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except BridgeError as e:
            payload = e.as_dict(name)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                "isError": True, "structuredContent": payload}}
        except Exception as e:
            payload = {"ok": False, "error_code": "TOOL_CALL_FAILED",
                       "message": "%s: %s" % (type(e).__name__, e), "tool": name}
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                "isError": True, "structuredContent": payload}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    _lock_stdio_utf8()
    log("starting; bridge=%s:%d token_file=%s" % (HOST, PORT, TOKEN_FILE))
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
