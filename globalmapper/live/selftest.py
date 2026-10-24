# -*- coding: utf-8 -*-
"""
selftest.py — Global Mapper MCP 服务端一键自检（纯标准库，无需 Global Mapper）

启动 live/mcp_server.py 一个子进程（带 GM_BRIDGE_TOKEN），自动检查五项：
  1) initialize  —— MCP 握手与 serverInfo（版本应为 0.1.x）
  2) tools/list  —— 7 个 globalmapper_* 工具齐全
  3) bad-token   —— 设置了 GM_BRIDGE_TOKEN 时，不带 _token 的调用必须
                    被 BAD_TOKEN 拒绝
  4) ping        —— 带正确 _token 时拿到 pong（无模块时 module_found=false
                    亦合格，本自检只验协议层与结构化回报）
  5) discover    —— 无模块时也应结构化回报 module_found=false
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
注意：自检不验证与 Global Mapper 本体的对接（模块签名、脚本上下文），
实机校准按 docs/CALIBRATION.md 进行。
"""
import json
import os
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_PY = os.path.join(HERE, "mcp_server.py")
TEST_TOKEN = "selftest-token-0123456789"

EXPECTED_TOOLS = {
    "globalmapper_ping", "globalmapper_discover", "globalmapper_workspace_info",
    "globalmapper_list_layers", "globalmapper_set_layer_visible",
    "globalmapper_zoom_to_layer", "globalmapper_export_workspace_image",
}

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""), flush=True)


def read_line_timeout(stream, timeout=15):
    fd = stream.fileno()
    buf = b""
    deadline = time.time() + timeout
    while b"\n" not in buf:
        if time.time() > deadline:
            raise TimeoutError("等待 MCP 响应超时")
        r, _w, _x = select.select([fd], [], [], 1)
        if not r:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            raise EOFError("MCP 进程已退出")
        buf += chunk
    return buf.split(b"\n", 1)[0].decode("utf-8")


class McpClient:
    def __init__(self, proc):
        self.proc = proc
        self._id = 0

    def request(self, method, params=None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        return json.loads(read_line_timeout(self.proc.stdout))

    def notify(self, method):
        msg = {"jsonrpc": "2.0", "method": method}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def call_tool(self, name, args=None, token=None):
        arguments = dict(args or {})
        if token is not None:
            arguments["_token"] = token
        return self.request("tools/call",
                            {"name": name, "arguments": arguments})


def tool_text(resp):
    result = resp.get("result") or {}
    parts = result.get("content") or []
    return "".join(p.get("text", "") for p in parts), result.get("isError")


def main():
    env = dict(os.environ)
    env["GM_BRIDGE_TOKEN"] = TEST_TOKEN
    mcp = subprocess.Popen([sys.executable, MCP_PY],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, env=env)
    try:
        client = McpClient(mcp)

        # 1) initialize
        try:
            resp = client.request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "0"}})
            info = (resp.get("result") or {}).get("serverInfo") or {}
            ok = info.get("name") == "globalmapper-bridge" and \
                str(info.get("version", "")).startswith("0.1")
            report("1-initialize", ok, "serverInfo=%s" % info)
            client.notify("notifications/initialized")
        except Exception as e:
            report("1-initialize", False, str(e))

        # 2) tools/list —— 7 个工具
        try:
            resp = client.request("tools/list")
            names = {t["name"] for t in (resp.get("result") or {}).get("tools", [])}
            missing = EXPECTED_TOOLS - names
            extra = names - EXPECTED_TOOLS
            report("2-tools-list", not missing and not extra,
                   "共 %d 个工具%s%s" % (
                       len(names),
                       ("，缺: %s" % sorted(missing)) if missing else "",
                       ("，多: %s" % sorted(extra)) if extra else ""))
        except Exception as e:
            report("2-tools-list", False, str(e))

        # 3) bad-token：不带 _token 必须被拒
        try:
            text, is_err = tool_text(client.call_tool("globalmapper_ping"))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("3-bad-token", ok, text.strip().replace("\n", " ")[:120])
        except Exception as e:
            report("3-bad-token", False, str(e))

        # 4) ping（带正确 token）
        try:
            text, is_err = tool_text(
                client.call_tool("globalmapper_ping", token=TEST_TOKEN))
            ok = (not is_err) and '"pong": true' in text
            report("4-ping", ok, text.strip().replace("\n", " ")[:120])
        except Exception as e:
            report("4-ping", False, str(e))

        # 5) discover（无模块环境：结构化回报 module_found 即合格）
        try:
            text, is_err = tool_text(
                client.call_tool("globalmapper_discover", token=TEST_TOKEN))
            ok = (not is_err) and '"module_found"' in text and '"context"' in text
            report("5-discover", ok, text.strip().replace("\n", " ")[:160])
        except Exception as e:
            report("5-discover", False, str(e))
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
