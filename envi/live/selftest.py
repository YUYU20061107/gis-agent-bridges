# -*- coding: utf-8 -*-
"""
selftest.py — ENVI 无头桥一键自检（纯标准库，无需 ENVI）

本包没有应用内桥，自检只启动 live/mcp_server.py 一个子进程，并给它设置
测试用 ENVI_BRIDGE_TOKEN 以便同时验证 token 闸。检查六项：
  1) initialize          —— MCP 握手与 serverInfo（envi-headless-bridge 0.2.x）
  2) tools/list          —— 7 个 envi_* 工具齐全
  3) tools/call ping     —— 带正确 token 时拿到 pong
  4) tools/call discover —— 无 ENVI 时也应结构化回报（envi_available=false 即合格）
  5) run_task 闸门       —— 不带 confirm=true 必须被 CONFIRM_REQUIRED 闸住
  6) 错误 token          —— _meta.token 不对必须被 BAD_TOKEN 拒绝
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_PY = os.path.join(HERE, "mcp_server.py")
TEST_TOKEN = "selftest-token-0123456789"

EXPECTED_TOOLS = {
    "envi_ping", "envi_discover", "envi_raster_info", "envi_list_tasks",
    "envi_describe_task", "envi_run_task", "envi_export_raster_subset",
}

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""), flush=True)


class _LineReader:
    """逐行读取子进程 stdout。

    Windows 上 select() 只接受 socket，管道句柄会报 WinError 10038，
    因此改用后台线程 + 队列，跨平台行为一致。
    """

    def __init__(self, stream):
        self._q = queue.Queue()
        threading.Thread(target=self._pump, args=(stream,), daemon=True).start()

    def _pump(self, stream):
        try:
            while True:
                line = stream.readline()
                if not line:
                    self._q.put(None)
                    return
                self._q.put(line)
        except Exception as e:  # 交给读端抛出，避免线程里静默
            self._q.put(e)

    def readline(self, timeout=15):
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("等待 MCP 响应超时")
        if item is None:
            raise EOFError("MCP 进程已退出")
        if isinstance(item, Exception):
            raise item
        return item.decode("utf-8").rstrip("\r\n")


class McpClient:
    def __init__(self, proc, token):
        self.proc = proc
        self.token = token
        self._id = 0
        self._reader = _LineReader(proc.stdout)

    def request(self, method, params=None, token="__default__"):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        if method == "tools/call":
            tok = self.token if token == "__default__" else token
            if tok:
                msg["params"] = dict(msg.get("params") or {})
                msg["params"]["_meta"] = {"token": tok}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        return json.loads(self._reader.readline(15))

    def notify(self, method):
        msg = {"jsonrpc": "2.0", "method": method}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def call_tool(self, name, args=None, token="__default__"):
        return self.request("tools/call",
                            {"name": name, "arguments": args or {}},
                            token=token)


def tool_text(resp):
    result = resp.get("result") or {}
    parts = result.get("content") or []
    return "".join(p.get("text", "") for p in parts), result.get("isError")


def main():
    env = dict(os.environ)
    env["ENVI_BRIDGE_TOKEN"] = TEST_TOKEN
    mcp = subprocess.Popen([sys.executable, MCP_PY],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, env=env)
    try:
        client = McpClient(mcp, TEST_TOKEN)

        # 1) initialize
        try:
            resp = client.request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "0"}})
            info = (resp.get("result") or {}).get("serverInfo") or {}
            ok = info.get("name") == "envi-headless-bridge" and \
                str(info.get("version", "")).startswith("0.2")
            report("1-initialize", ok, "serverInfo=%s" % info)
            client.notify("notifications/initialized")
        except Exception as e:
            report("1-initialize", False, str(e))

        # 2) tools/list
        try:
            resp = client.request("tools/list")
            names = {t["name"] for t in (resp.get("result") or {}).get("tools", [])}
            missing = EXPECTED_TOOLS - names
            report("2-tools-list", not missing,
                   "共 %d 个工具%s" % (len(names),
                                       ("，缺: %s" % sorted(missing)) if missing else ""))
        except Exception as e:
            report("2-tools-list", False, str(e))

        # 3) ping（正确 token）
        try:
            text, _is_err = tool_text(client.call_tool("envi_ping"))
            report("3-ping", '"pong": true' in text, text.strip()[:120])
        except Exception as e:
            report("3-ping", False, str(e))

        # 4) discover（无 ENVI 环境：envi_available=false 的结构化回报即合格）
        try:
            text, _is_err = tool_text(client.call_tool("envi_discover"))
            ok = '"envi_available"' in text and '"mode": "headless"' in text
            report("4-discover", ok, text.strip().replace("\n", " ")[:160])
        except Exception as e:
            report("4-discover", False, str(e))

        # 5) run_task 闸门：不带 confirm 必须被闸住（且不得谎称已执行）
        try:
            text, _is_err = tool_text(client.call_tool(
                "envi_run_task", {"task": "SpectralIndex", "params": {}}))
            ok = '"error_code": "CONFIRM_REQUIRED"' in text
            report("5-run-task-gate", ok, text.strip().replace("\n", " ")[:140])
        except Exception as e:
            report("5-run-task-gate", False, str(e))

        # 6) 错误 token 必须被拒
        try:
            text, _is_err = tool_text(client.call_tool(
                "envi_ping", {}, token="definitely-wrong-token"))
            ok = '"error_code": "BAD_TOKEN"' in text
            report("6-bad-token", ok, text.strip().replace("\n", " ")[:120])
        except Exception as e:
            report("6-bad-token", False, str(e))
    finally:
        if mcp.poll() is None:
            mcp.terminate()
            try:
                mcp.wait(timeout=5)
            except Exception:
                mcp.kill()
    passed = sum(1 for _n, ok in RESULTS if ok)
    print("SELFTEST: %d/%d PASS" % (passed, len(RESULTS)))
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
