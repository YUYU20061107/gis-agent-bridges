# -*- coding: utf-8 -*-
"""
mcp_server.py — FME 无头 runner MCP 服务端（stdio，纯标准库，v0.1）

定位：FME 没有"当前会话"接口，本服务端不接入任何 FME GUI 会话；它只在
本地以无头方式运行 .fmw workspace 文件——通过官方 Python API fmeobjects
的 FMEWorkspaceRunner，从外部进程把 workspace 跑起来。服务器场景（发布、
调度、权限治理）请使用 Safe Software 官方的 FME Flow MCP Server；本包只
补"本地桌面授权下直接跑 .fmw 文件"这一窄缝，定位互补，不与官方竞争。

工具（6 个）：
  只读：fme_ping / fme_discover / fme_list_workspaces / fme_workspace_info /
        fme_workspace_log_tail
  执行（须 confirm=true）：fme_run_workspace
  —— confirm 只能在用户明确同意后由 Agent 填入；无 fmeobjects 时
     run_workspace 返回 FME_NOT_AVAILABLE，绝不假装执行成功。

运行前提：本服务端进程所用的 Python 解释器要能 import 到 fmeobjects
（FME 自带 Python，或已把 FME 安装目录配进环境）。服务端自身只用标准库；
fme_discover 会如实回报探测到的安装候选与导入尝试结果。

可选 token 守卫：设置环境变量 FME_BRIDGE_TOKEN，或在
~/.fme-agent-bridge.token 存放 token，则每次 tools/call 须在参数里带
_token 且一致，否则以 BAD_TOKEN 拒绝。未配置 token 时按 stdio 本地信任
运行（与典型本地 MCP 服务端一致），请勿把本服务端暴露到网络。

环境变量：
  FME_BRIDGE_TOKEN            可选 token（优先于 token 文件）
  FME_BRIDGE_WORKSPACE_DIR    list_workspaces 的默认扫描目录
每次运行都会追加一条记录到 ~/.fme-agent-bridge/runs.jsonl（运行日志）。
日志写 stderr，stdout 只走 MCP 协议。
"""
import json
import os
import sys
import time
from datetime import datetime

PROTOCOL_VERSION = "2024-11-05"
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".fme-agent-bridge.token")
JOURNAL_DIR = os.path.join(os.path.expanduser("~"), ".fme-agent-bridge")
JOURNAL_FILE = os.path.join(JOURNAL_DIR, "runs.jsonl")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))


def log(*a):
    print("[fme-mcp]", *a, file=sys.stderr, flush=True)


def expected_token():
    tok = os.environ.get("FME_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def journal(entry):
    try:
        os.makedirs(JOURNAL_DIR, exist_ok=True)
        entry = dict(entry)
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------ fmeobjects
def load_fmeobjects():
    """多策略导入 fmeobjects，返回 (module, attempts)。"""
    attempts = []
    try:
        import fmeobjects
        return fmeobjects, ["import fmeobjects: ok"]
    except Exception as e:
        attempts.append("import fmeobjects: fail: %s" % e)
    try:
        from fme_bridge import install_candidates
        cands = [d for _s, d in install_candidates()]
    except Exception:
        cands = []
        home = os.environ.get("FME_HOME")
        if home:
            cands.append(home)
    for d in cands:
        for sub in ("", "python"):
            p = os.path.join(d, sub) if sub else d
            if not os.path.isdir(p) or p in sys.path:
                continue
            sys.path.insert(0, p)
            try:
                import fmeobjects
                attempts.append("import via %s: ok" % p)
                return fmeobjects, attempts
            except Exception as e:
                attempts.append("import via %s: fail: %s" % (p, e))
                sys.path.remove(p)
    return None, attempts


def fme_available():
    mod, _attempts = load_fmeobjects()
    return mod is not None


# ------------------------------------------------------------------ tools
def tool_ping(args):
    return {"ok": True, "pong": True, "bridge": "fme-headless-runner",
            "version": "0.1.0", "mode": "headless-runner",
            "fme_available": fme_available()}


def tool_discover(args):
    mod, attempts = load_fmeobjects()
    info = {"ok": True, "mode": "headless-runner", "session_api": False,
            "session_note": "FME 无当前会话接口，本包只做本地无头运行 .fmw 文件",
            "fme_available": mod is not None, "import_attempts": attempts,
            "fme_home_env": os.environ.get("FME_HOME"),
            "journal_file": JOURNAL_FILE,
            "official_note": "服务器场景请用 Safe Software 官方 FME Flow "
                             "MCP Server；本包只补本地桌面授权下跑 .fmw 的窄缝"}
    if mod is not None:
        info["fmeobjects_file"] = getattr(mod, "__file__", "unknown")
        runner = getattr(mod, "FMEWorkspaceRunner", None)
        info["runner_methods"] = (sorted(n for n in dir(runner)
                                         if not n.startswith("_"))
                                  if runner is not None else [])
    try:
        from fme_bridge import candidate_status
        info["install_candidates"] = candidate_status()
    except Exception as e:
        info["install_candidates_error"] = str(e)
    info["default_workspace_dir"] = os.environ.get(
        "FME_BRIDGE_WORKSPACE_DIR") or os.getcwd()
    return info


def _scan_dir(root):
    items = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".fmw") and ".bak-" not in fn.lower():
                p = os.path.join(dirpath, fn)
                st = os.stat(p)
                items.append({"name": fn, "path": p, "bytes": st.st_size,
                              "mtime": datetime.fromtimestamp(
                                  st.st_mtime).isoformat(timespec="seconds")})
    items.sort(key=lambda x: x["path"])
    return items


def tool_list_workspaces(args):
    root = args.get("directory") or os.environ.get(
        "FME_BRIDGE_WORKSPACE_DIR") or os.getcwd()
    if not os.path.isdir(root):
        return {"ok": False, "error_code": "DIR_NOT_FOUND",
                "message": "目录不存在: %s" % root}
    items = _scan_dir(root)
    return {"ok": True, "directory": root, "count": len(items),
            "workspaces": items}


def tool_workspace_info(args):
    path = args.get("path")
    if not path or not os.path.isfile(path):
        return {"ok": False, "error_code": "WORKSPACE_NOT_FOUND",
                "message": "workspace 文件不存在: %s" % path}
    try:
        from fme_bridge import parse_fmw_file
        result = parse_fmw_file(path)
    except Exception as e:
        return {"ok": False, "error_code": "PARSE_FAILED",
                "message": "解析失败: %s" % e}
    result.update({"ok": True, "path": path})
    return result


def _log_candidates(path):
    cands = []
    if path:
        stem, _ext = os.path.splitext(path)
        cands += [stem + ".log", stem + "_log.txt", path + ".log"]
    return cands


def tool_run_workspace(args):
    path = args.get("path")
    params = args.get("parameters") or {}
    if not isinstance(params, dict):
        return {"ok": False, "ran": False, "error_code": "BAD_PARAMETERS",
                "message": "parameters 必须是 JSON 对象（published parameters）"}
    if args.get("confirm") is not True:
        return {"ok": True, "ran": False,
                "reason": "run_workspace 需要 confirm=true 显式确认：运行 "
                          "workspace 会按其定义真实读写数据，confirm 只能在"
                          "用户明确同意后填入"}
    if not path or not os.path.isfile(path):
        return {"ok": False, "ran": False, "error_code": "WORKSPACE_NOT_FOUND",
                "message": "workspace 文件不存在: %s" % path}
    mod, attempts = load_fmeobjects()
    if mod is None:
        journal({"tool": "run_workspace", "workspace": path,
                 "status": "not_available", "parameters": params})
        return {"ok": False, "ran": False, "error_code": "FME_NOT_AVAILABLE",
                "message": "本机无法导入 fmeobjects，未执行任何 workspace",
                "import_attempts": attempts}
    runner_cls = getattr(mod, "FMEWorkspaceRunner", None)
    if runner_cls is None:
        journal({"tool": "run_workspace", "workspace": path,
                 "status": "not_available", "parameters": params})
        return {"ok": False, "ran": False, "error_code": "FMEOBJECTS_INCOMPLETE",
                "message": "fmeobjects 缺少 FMEWorkspaceRunner，未执行",
                "import_attempts": attempts}
    t0 = time.time()
    try:
        runner = runner_cls()
        if params:
            ret = runner.runWithParameters(path, params)
            via = "runWithParameters"
        else:
            ret = runner.run(path)
            via = "run"
    except Exception as e:
        journal({"tool": "run_workspace", "workspace": path,
                 "status": "failed", "parameters": params, "error": str(e)})
        return {"ok": False, "ran": False, "error_code": "FME_RUN_FAILED",
                "message": "FMEWorkspaceRunner 报错: %s" % e,
                "duration_s": round(time.time() - t0, 3)}
    duration = round(time.time() - t0, 3)
    journal({"tool": "run_workspace", "workspace": path, "status": "ok",
             "parameters": params, "duration_s": duration, "via": via})
    return {"ok": True, "ran": True, "workspace": path, "via": via,
            "parameters": params, "duration_s": duration,
            "runner_return": repr(ret)[:200],
            "log_files_found": [c for c in _log_candidates(path)
                                if os.path.isfile(c)],
            "journal_file": JOURNAL_FILE}


def tool_workspace_log_tail(args):
    path = args.get("path")
    n = args.get("lines") or 50
    try:
        n = max(1, min(int(n), 1000))
    except Exception:
        n = 50
    tried = []
    explicit = args.get("log_path")
    cands = ([explicit] if explicit else []) + _log_candidates(path)
    for c in cands:
        tried.append(c)
        if c and os.path.isfile(c):
            with open(c, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            return {"ok": True, "source": c, "total_lines": len(lines),
                    "lines": lines[-n:]}
    # 回退：桥自己的运行日志里该 workspace 的记录
    if os.path.isfile(JOURNAL_FILE):
        with open(JOURNAL_FILE, "r", encoding="utf-8", errors="replace") as f:
            entries = [ln for ln in f.read().splitlines() if ln.strip()]
        if path:
            entries = [ln for ln in entries if path in ln]
        if entries:
            return {"ok": True, "source": "bridge-journal",
                    "path": JOURNAL_FILE, "total_lines": len(entries),
                    "lines": entries[-n:]}
    return {"ok": False, "error_code": "NO_LOG_FOUND",
            "message": "未找到运行日志；workspace 可能尚未经本桥运行过",
            "tried": tried, "journal_file": JOURNAL_FILE}


_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_INT = {"type": "integer"}

TOOL_DEFS = [
    ("fme_ping", "连通性检查：runner 是否在线，并回报 fmeobjects 是否可用", {}),
    ("fme_discover", "环境发现：fmeobjects 导入尝试、FME 安装候选、运行日志位置（校准用）", {}),
    ("fme_list_workspaces", "列出目录下全部 .fmw workspace（名称、路径、大小、修改时间）",
     {"directory": dict(_STR, description="扫描目录（可选，缺省用 FME_BRIDGE_WORKSPACE_DIR 或当前目录）")}),
    ("fme_workspace_info", "解析一个 .fmw：源/目标数据集与 transformer 计数（文本尽力解析，可能不完整）",
     {"path": dict(_STR, description=".fmw 路径（必填）")}),
    ("fme_run_workspace", "【执行·须 confirm=true】以无头方式运行一个 .fmw；parameters 传 published parameters 的 JSON 对象；无 fmeobjects 时返回 FME_NOT_AVAILABLE，绝不假装成功",
     {"path": dict(_STR, description=".fmw 路径（必填）"),
      "parameters": {"type": "object", "description": "published parameters（可选，JSON 对象）"},
      "confirm": dict(_BOOL, description="必须为 true 才执行")}),
    ("fme_workspace_log_tail", "读某 workspace 最近运行日志的尾部（FME 日志文件或本桥运行日志）",
     {"path": dict(_STR, description=".fmw 路径（可选）"),
      "log_path": dict(_STR, description="日志文件路径（可选，优先）"),
      "lines": dict(_INT, description="尾部行数（可选，默认 50）")}),
]

HANDLERS = {
    "fme_ping": tool_ping,
    "fme_discover": tool_discover,
    "fme_list_workspaces": tool_list_workspaces,
    "fme_workspace_info": tool_workspace_info,
    "fme_run_workspace": tool_run_workspace,
    "fme_workspace_log_tail": tool_workspace_log_tail,
}


def tools_list():
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props}}
            for name, desc, props in TOOL_DEFS]


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fme-headless-runner", "version": "0.1.0"}}}
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
        supplied = args.pop("_token", None)
        expect = expected_token()
        if expect and supplied != expect:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(
                    {"ok": False, "error_code": "BAD_TOKEN",
                     "message": "token 缺失或不正确"}, ensure_ascii=False)}],
                "isError": True}}
        handler = HANDLERS.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "unknown tool: %s" % name}],
                "isError": True}}
        try:
            result = handler(args)
            text = json.dumps(result, ensure_ascii=False, indent=2)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": "tool failed: %s" % e}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    log("starting; journal=%s token_guard=%s" % (
        JOURNAL_FILE, "on" if expected_token() else "off"))
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
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
