# -*- coding: utf-8 -*-
"""
selftest.py — FME 无头 runner 一键自检（纯标准库，无需 FME）

启动 live/mcp_server.py 一个子进程（带自检 token 守卫），自动检查：
  1) initialize      —— MCP 握手与 serverInfo（fme-headless-runner 0.2.x）
  2) tools/list      —— 6 个 fme_* 工具齐全
  3) tools/call ping —— 拿到 pong
  4) tools/call discover —— 结构化回报（含 fme_available 字段；无 FME 时为 false 即合格）
  5a) run 闸门       —— run_workspace 不带 confirm 必须被闸住（ran=false）
  5b) bad-token      —— 错误 _token 调用必须被 BAD_TOKEN 拒绝
  6) run 诚实性      —— 对临时假 .fmw 带 confirm 调用：无 FME 时必须报
                        FME_NOT_AVAILABLE / FME_RUN_FAILED 且 ran=false，
                        绝不许报 ran=true（有 FME 的机器上假文件会真跑并失败，同判）
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
自检会在用户目录的桥运行日志里留下第 6 项的记录条目，属预期行为。
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_PY = os.path.join(HERE, "mcp_server.py")
TEST_TOKEN = "fme-selftest-token"

EXPECTED_TOOLS = {
    "fme_ping", "fme_discover", "fme_list_workspaces", "fme_workspace_info",
    "fme_run_workspace", "fme_workspace_log_tail",
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
    （自 SuperMap 桥 live/selftest.py 实机校准结论迁移，2026-10-24。）
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

    def request(self, method, params=None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        return json.loads(self._reader.readline(15))

    def notify(self, method):
        msg = {"jsonrpc": "2.0", "method": method}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def call_tool(self, name, args=None, token="__default__"):
        args = dict(args or {})
        if token == "__default__":
            args["_token"] = self.token
        elif token is not None:
            args["_token"] = token
        return self.request("tools/call", {"name": name, "arguments": args})


def tool_text(resp):
    result = resp.get("result") or {}
    parts = result.get("content") or []
    return "".join(p.get("text", "") for p in parts), result.get("isError")


def main():
    env = dict(os.environ)
    env["FME_BRIDGE_TOKEN"] = TEST_TOKEN
    mcp = subprocess.Popen([sys.executable, MCP_PY], env=env,
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL)
    client = McpClient(mcp, TEST_TOKEN)
    try:
        # 1) initialize
        try:
            resp = client.request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "0"}})
            info = (resp.get("result") or {}).get("serverInfo") or {}
            ok = info.get("name") == "fme-headless-runner" and \
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
            extra = names - EXPECTED_TOOLS
            report("2-tools-list", not missing and not extra,
                   "共 %d 个工具%s%s" % (len(names),
                       ("，缺: %s" % sorted(missing)) if missing else "",
                       ("，多: %s" % sorted(extra)) if extra else ""))
        except Exception as e:
            report("2-tools-list", False, str(e))

        # 3) ping
        try:
            text, is_err = tool_text(client.call_tool("fme_ping"))
            report("3-ping", (not is_err) and '"pong": true' in text,
                   text.strip().replace("\n", " ")[:120])
        except Exception as e:
            report("3-ping", False, str(e))

        # 4) discover（无 FME 环境：fme_available=false 的结构化回报即合格）
        try:
            text, is_err = tool_text(client.call_tool("fme_discover"))
            ok = (not is_err) and '"fme_available"' in text
            report("4-discover", ok, text.strip().replace("\n", " ")[:160])
        except Exception as e:
            report("4-discover", False, str(e))

        # 5a) run 闸门：不带 confirm 必须被闸住
        try:
            text, is_err = tool_text(client.call_tool(
                "fme_run_workspace", {"path": "/nonexistent/x.fmw"}))
            ok = (not is_err) and '"ran": false' in text and "confirm" in text
            report("5a-run-gate", ok, text.strip().replace("\n", " ")[:120])
        except Exception as e:
            report("5a-run-gate", False, str(e))

        # 5b) 错误 token 必须被 BAD_TOKEN 拒绝
        try:
            text, is_err = tool_text(client.call_tool(
                "fme_ping", token="definitely-wrong-token"))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("5b-bad-token", ok, text.strip()[:120])
        except Exception as e:
            report("5b-bad-token", False, str(e))

        # 6) run 诚实性：假 .fmw + confirm，无 FME 时不许假装成功
        try:
            fd, fake = tempfile.mkstemp(suffix=".fmw")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("#! fake workspace for selftest\n")
            try:
                text, _is_err = tool_text(client.call_tool(
                    "fme_run_workspace", {"path": fake, "confirm": True}))
                ok = ('"ran": false' in text and
                      ("FME_NOT_AVAILABLE" in text or "FME_RUN_FAILED" in text))
                report("6-run-honesty", ok,
                       text.strip().replace("\n", " ")[:140])
            finally:
                os.remove(fake)
        except Exception as e:
            report("6-run-honesty", False, str(e))
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
