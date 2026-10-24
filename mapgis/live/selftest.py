# -*- coding: utf-8 -*-
"""
selftest.py — MapGIS 探针 MCP 服务端一键自检（纯标准库，无需 MapGIS）

只启动 live/mcp_server.py 一个子进程（本包没有应用内桥），自动检查五项：
  1) initialize            —— MCP 握手与 serverInfo（版本应为 0.1.x）
  2) tools/list            —— 恰好 3 个 mapgis_* 探针工具
  3) tools/call ping       —— 本地健康检查拿到 pong
  4) tools/call discover   —— 带正确 token 调用；无 MapGIS 环境时
                              python_found=false 的结构化回报即合格
  5) bad-token             —— 错误 token 调 discover 必须被 BAD_TOKEN 拒绝
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
自检只验证协议层与探针纪律，不验证任何 MapGIS API（那要等实机探针）。
token 文件（~/.mapgis-bridge.token）若原先存在，自检结束会原样恢复。
"""
import json
import os
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_PY = os.path.join(HERE, "mcp_server.py")
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".mapgis-bridge.token")

EXPECTED_TOOLS = {"mapgis_ping", "mapgis_discover", "mapgis_probe_environment"}

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""), flush=True)


def read_line_timeout(stream, timeout=30):
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

    def call_tool(self, name, args=None):
        return self.request("tools/call",
                            {"name": name, "arguments": args or {}})


def tool_text(resp):
    result = resp.get("result") or {}
    parts = result.get("content") or []
    return "".join(p.get("text", "") for p in parts), result.get("isError")


def wait_token_file(timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(TOKEN_FILE):
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                tok = f.read().strip()
            if tok:
                return tok
        time.sleep(0.2)
    return None


def main():
    token_backup = None
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            token_backup = f.read()
        # 服务端会复用已有 token；为保证自检拿到的是本轮 token，先移走旧文件，
        # 结束时按原样恢复。
        os.remove(TOKEN_FILE)
    mcp = None
    try:
        mcp = subprocess.Popen([sys.executable, MCP_PY],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
        client = McpClient(mcp)
        token = wait_token_file()
        if token is None:
            report("server-startup", False, "token 文件未在时限内生成")
            return _finish(mcp, token_backup)

        # 1) initialize
        try:
            resp = client.request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "0"}})
            info = (resp.get("result") or {}).get("serverInfo") or {}
            ok = info.get("name") == "mapgis-probe-bridge" and \
                str(info.get("version", "")).startswith("0.1")
            report("1-initialize", ok, "serverInfo=%s" % info)
            client.notify("notifications/initialized")
        except Exception as e:
            report("1-initialize", False, str(e))

        # 2) tools/list —— 恰好 3 个
        try:
            resp = client.request("tools/list")
            names = {t["name"] for t in (resp.get("result") or {}).get("tools", [])}
            report("2-tools-list", names == EXPECTED_TOOLS,
                   "共 %d 个工具: %s" % (len(names), sorted(names)))
        except Exception as e:
            report("2-tools-list", False, str(e))

        # 3) ping（健康检查，不要求 token）
        try:
            text, is_err = tool_text(client.call_tool("mapgis_ping"))
            report("3-ping", (not is_err) and '"pong": true' in text,
                   text.strip()[:120])
        except Exception as e:
            report("3-ping", False, str(e))

        # 4) discover（带正确 token；无 MapGIS 时结构化回报即合格）
        try:
            text, is_err = tool_text(
                client.call_tool("mapgis_discover", {"token": token}))
            ok = (not is_err) and '"python_found"' in text
            report("4-discover", ok, text.strip().replace("\n", " ")[:160])
        except Exception as e:
            report("4-discover", False, str(e))

        # 5) bad-token：错误 token 必须被 BAD_TOKEN 拒绝
        try:
            text, is_err = tool_text(client.call_tool(
                "mapgis_discover", {"token": "definitely-wrong-token"}))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("5-bad-token", ok, text.strip()[:120])
        except Exception as e:
            report("5-bad-token", False, str(e))
    finally:
        pass
    return _finish(mcp, token_backup)


def _finish(mcp, token_backup):
    if mcp is not None and mcp.poll() is None:
        mcp.terminate()
        try:
            mcp.wait(timeout=5)
        except Exception:
            mcp.kill()
    if token_backup is not None:
        with open(TOKEN_FILE, "wb") as f:
            f.write(token_backup)
    elif os.path.isfile(TOKEN_FILE):
        try:
            os.remove(TOKEN_FILE)
        except Exception:
            pass
    passed = sum(1 for _n, ok in RESULTS if ok)
    print("SELFTEST: %d/%d PASS" % (passed, len(RESULTS)))
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
