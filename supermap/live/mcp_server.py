# -*- coding: utf-8 -*-
"""
mcp_server.py — MCP 服务端（stdio，纯标准库，v0.3）

把 MCP 工具调用转发到 iDesktopX 内的应用内桥（inapp_bridge.py，127.0.0.1:47615）。
注册到你的 AI Agent / MCP 客户端的 MCP 配置后，Agent 即可用下列工具操作 iDesktopX 当前工作空间：
  只读：supermap_ping / supermap_discover / supermap_workspace_info /
        supermap_list_datasources / supermap_list_datasets / supermap_list_maps /
        supermap_list_layers / supermap_export_map_image
  视图级（只改显示、可逆）：supermap_set_layer_visible / supermap_zoom_to_dataset
  写类（须 confirm=true）：supermap_add_dataset_to_map / supermap_make_label_thematic /
        supermap_save_workspace
v0.3 的操作类工具为实验性实现，未在真实 iDesktopX 上验证（iDesktop 10i 文件回退
模式已实机校准，见 docs/CALIBRATION-RESULTS-20261024.md）；桥侧调不通时会
返回结构化错误，Agent 必须如实回报，不许把错误说成成功。

环境变量：
  SM_BRIDGE_HOST（默认 127.0.0.1）、SM_BRIDGE_PORT（默认 47615）、
  SM_BRIDGE_TOKEN（优先；否则读 SM_BRIDGE_TOKEN_FILE 或 ~/.supermap-live-bridge.token）

自动启动（用时必开）：
  SM_BRIDGE_AUTOSTART=1
  SM_BRIDGE_AUTOSTART_WORKSPACE=<默认工作空间 .smwu 路径>
  SM_BRIDGE_AUTOSTART_PYTHON=<带 iobjectspy 的 Python 路径；未配置则自动启动不可用>
  SM_BRIDGE_LOG_FILE=<桥日志，默认 token 文件同目录 bridge.log>
  当桥端口不通时，首次 tools/call 会自动在工作空间**副本**上拉起桥（不碰原件）。

日志写 stderr，stdout 只走 MCP 协议。
"""
import io
import json
import os
import socket
import subprocess
import sys
import time

HOST = os.environ.get("SM_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("SM_BRIDGE_PORT", "47615"))
TOKEN_FILE = os.environ.get("SM_BRIDGE_TOKEN_FILE") or \
    os.path.join(os.path.expanduser("~"), ".supermap-live-bridge.token")
PROTOCOL_VERSION = "2024-11-05"

# ---- 自动启动配置（缺省全部关闭，只做“用时必开”，不改变桥的安全边界） ----
AUTOSTART = os.environ.get("SM_BRIDGE_AUTOSTART", "").strip().lower() in ("1", "true", "yes", "on")
AUTOSTART_WORKSPACE = os.environ.get("SM_BRIDGE_AUTOSTART_WORKSPACE", "").strip()
AUTOSTART_PYTHON = os.environ.get("SM_BRIDGE_AUTOSTART_PYTHON", "").strip()
BRIDGE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_bridge_copy.py")
LOG_FILE = os.environ.get("SM_BRIDGE_LOG_FILE") or \
    os.path.join(os.path.dirname(TOKEN_FILE), "bridge.log")

_AUTOSTART = {"child": None, "spawned": False}


def log(*a):
    print("[supermap-mcp]", *a, file=sys.stderr, flush=True)

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



def _port_open(timeout=1):
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except Exception:
        return False


def ensure_bridge(wait_seconds=90):
    """桥没在跑且配置了自动启动时，在副本上拉起桥并等它就绪。"""
    if _port_open():
        return True
    if not AUTOSTART or not AUTOSTART_WORKSPACE:
        return False
    if not (os.path.isfile(AUTOSTART_WORKSPACE) and os.path.isfile(BRIDGE_SCRIPT)
            and os.path.isfile(AUTOSTART_PYTHON)):
        log("autostart skipped: missing workspace / bridge script / python")
        return False
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir and not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        fh = open(LOG_FILE, "ab", buffering=0)
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        child = subprocess.Popen([AUTOSTART_PYTHON, BRIDGE_SCRIPT, AUTOSTART_WORKSPACE],
                                 stdin=subprocess.DEVNULL, stdout=fh, stderr=fh,
                                 creationflags=flags,
                                 cwd=(log_dir if log_dir and os.path.isdir(log_dir)
                                      else os.path.dirname(TOKEN_FILE) or None))
        _AUTOSTART["child"] = child
        _AUTOSTART["spawned"] = True
        log("autostart bridge pid=%s workspace=%s" % (child.pid, AUTOSTART_WORKSPACE))
    except Exception as e:
        log("autostart failed:", e)
        return False
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _port_open():
            log("autostart bridge ready")
            return True
        if _AUTOSTART["child"].poll() is not None:
            log("autostart bridge exited code=%s (see %s)" % (_AUTOSTART["child"].returncode, LOG_FILE))
            return False
        time.sleep(1)
    log("autostart timeout after %ss" % wait_seconds)
    return False


def get_token():
    tok = os.environ.get("SM_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def call_bridge(tool, args):
    payload = {"token": get_token(), "tool": tool, "args": args or {}}
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.create_connection((HOST, PORT), timeout=30) as s:
        s.sendall(data)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    resp = json.loads(buf.decode("utf-8"))
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error", "bridge error"))
    return resp.get("result")


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}

TOOL_DEFS = [
    ("supermap_ping", "连通性检查：桥是否在线", {}),
    ("supermap_discover", "发现 iDesktopX 当前工作空间的接入方式并回报现场 API 信息（校准用）", {}),
    ("supermap_workspace_info", "当前工作空间概览：数据源数、地图数、接入模式", {}),
    ("supermap_list_datasources", "列出当前工作空间的全部数据源（别名、引擎）", {}),
    ("supermap_list_datasets", "列出数据集；可传 datasource 只看某数据源",
     {"datasource": dict(_STR, description="数据源别名（可选）")}),
    ("supermap_list_maps", "列出当前工作空间的全部地图名", {}),
    ("supermap_list_layers", "列出某地图的图层（下标、名称、显隐）；map 省略时取第一幅地图",
     {"map": dict(_STR, description="地图名（可选）")}),
    ("supermap_add_dataset_to_map", "【写·实验性】把数据集加入地图，须 confirm=true；调不通会如实报错",
     {"datasource": dict(_STR, description="数据源别名（可选）"),
      "dataset": dict(_STR, description="数据集名（必填）"),
      "map": dict(_STR, description="地图名（可选，省略取第一幅）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("supermap_set_layer_visible", "【视图级·实验性】设置图层显隐，只改显示状态、可逆",
     {"map": dict(_STR, description="地图名（可选）"),
      "layer": dict(_STR, description="图层名或下标（数字字符串）"),
      "visible": dict(_BOOL, description="true=显示，false=隐藏")}),
    ("supermap_zoom_to_dataset", "【视图级·实验性】把地图视图缩放到数据集范围；做不到会报 NOT_SUPPORTED",
     {"datasource": dict(_STR, description="数据源别名（可选）"),
      "dataset": dict(_STR, description="数据集名（必填）"),
      "map": dict(_STR, description="地图名（可选）")}),
    ("supermap_make_label_thematic", "【写·实验性】按字段做标签专题图（如 NAME），须 confirm=true",
     {"map": dict(_STR, description="地图名（可选）"),
      "dataset": dict(_STR, description="数据集名（用于定位图层或新建专题图层）"),
      "layer": dict(_STR, description="已有图层名（可选，与 dataset 二选一优先）"),
      "field": dict(_STR, description="标签字段名（必填，如 NAME）"),
      "datasource": dict(_STR, description="数据源别名（可选）"),
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("supermap_export_map_image", "【实验性】把地图导出为 PNG 到指定路径，以文件真实落盘为准",
     {"map": dict(_STR, description="地图名（可选）"),
      "out_path": dict(_STR, description="PNG 输出路径（必填，目录须已存在）"),
      "width": dict(_INT, description="宽度像素（可选）"),
      "height": dict(_INT, description="高度像素（可选）")}),
    ("supermap_save_workspace", "保存当前工作空间（写操作，必须 confirm=true）",
     {"confirm": dict(_BOOL, description="必须为 true 才执行")}),
]

BRIDGE_TOOL = {name: name.replace("supermap_", "", 1) for name, _, _ in TOOL_DEFS}


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
            "serverInfo": {"name": "supermap-live-bridge", "version": "0.3.0"}}}
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
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "unknown tool: %s" % name}],
                "isError": True}}
        try:
            # 用时必开：桥没在跑且允许自动启动时，先在副本上拉起桥再调用
            if not _port_open():
                started = ensure_bridge()
                if not started and AUTOSTART:
                    return {"jsonrpc": "2.0", "id": mid, "result": {
                        "content": [{"type": "text", "text":
                                     "桥未运行，自动启动失败。检查 SM_BRIDGE_AUTOSTART_WORKSPACE 是否存在；"
                                     "日志: %s" % LOG_FILE}],
                        "isError": True}}
            result = call_bridge(BRIDGE_TOOL[name], args)
            text = json.dumps(_to_text(result), ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "bridge call failed: %s" % e}],
                "isError": True}}
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
