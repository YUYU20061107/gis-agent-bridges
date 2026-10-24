# -*- coding: utf-8 -*-
"""
selftest.py — 实时桥一键自检（纯标准库，无需 SuperMap）

在本机启动 inapp_bridge.py 与 mcp_server.py 两个子进程，自动检查五项：
  1) initialize        —— MCP 握手与 serverInfo（版本应为 0.3.x）
  2) tools/list        —— 13 个 supermap_* 工具齐全
  3) tools/call ping   —— 经桥转发并拿到 pong
  4) tools/call discover —— 无 SuperMap 时也应结构化回报（workspace_found=false 即合格）
  5) 安全闸门          —— save_workspace 不带 confirm 必须被闸住；
                          错误 token 直连桥必须被 BAD_TOKEN 拒绝
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
注意：若 47615 端口已被占用（可能已有桥在跑），自检会直接失败退出，不干扰现有桥。
桥的 token 文件（~/.supermap-live-bridge.token）若原先存在，自检结束会原样恢复。
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_PY = os.path.join(HERE, "inapp_bridge.py")
MCP_PY = os.path.join(HERE, "mcp_server.py")
HOST, PORT = "127.0.0.1", 47615
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".supermap-live-bridge.token")

EXPECTED_TOOLS = {
    "supermap_ping", "supermap_discover", "supermap_workspace_info",
    "supermap_list_datasources", "supermap_list_datasets", "supermap_list_maps",
    "supermap_list_layers", "supermap_add_dataset_to_map",
    "supermap_set_layer_visible", "supermap_zoom_to_dataset",
    "supermap_make_label_thematic", "supermap_export_map_image",
    "supermap_save_workspace",
}

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""), flush=True)


def port_open():
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            return True
    except Exception:
        return False


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
    def __init__(self, proc):
        self.proc = proc
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

    def call_tool(self, name, args=None):
        return self.request("tools/call",
                            {"name": name, "arguments": args or {}})


def tool_text(resp):
    result = resp.get("result") or {}
    parts = result.get("content") or []
    return "".join(p.get("text", "") for p in parts), result.get("isError")


def main():
    if port_open():
        print("[FAIL] 端口 %d 已被占用：可能已有实时桥在运行，自检不干扰它，请关掉后重跑" % PORT)
        return 1
    token_backup = None
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            token_backup = f.read()
    bridge = None
    mcp = None
    try:
        bridge = subprocess.Popen([sys.executable, BRIDGE_PY],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while time.time() < deadline:
            if bridge.poll() is not None:
                report("bridge-startup", False, "桥进程提前退出，退出码 %s" % bridge.returncode)
                return _finish(bridge, mcp, token_backup)
            if port_open() and os.path.isfile(TOKEN_FILE):
                break
            time.sleep(0.3)
        else:
            report("bridge-startup", False, "20 秒内桥未监听或 token 文件未生成")
            return _finish(bridge, mcp, token_backup)

        mcp = subprocess.Popen([sys.executable, MCP_PY],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
        client = McpClient(mcp)

        # 1) initialize
        try:
            resp = client.request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "0"}})
            info = (resp.get("result") or {}).get("serverInfo") or {}
            ok = info.get("name") == "supermap-live-bridge" and \
                str(info.get("version", "")).startswith("0.3")
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

        # 3) ping
        try:
            text, is_err = tool_text(client.call_tool("supermap_ping"))
            report("3-ping", (not is_err) and '"pong": true' in text, text.strip()[:120])
        except Exception as e:
            report("3-ping", False, str(e))

        # 4) discover（无 SuperMap 环境：workspace_found=false 的结构化回报即合格）
        try:
            text, is_err = tool_text(client.call_tool("supermap_discover"))
            ok = (not is_err) and '"workspace_found"' in text
            report("4-discover", ok, text.strip().replace("\n", " ")[:160])
        except Exception as e:
            report("4-discover", False, str(e))

        # 5a) save 闸门：不带 confirm 必须被闸住
        try:
            text, is_err = tool_text(client.call_tool("supermap_save_workspace", {}))
            ok = (not is_err) and '"saved": false' in text and "confirm" in text
            report("5a-save-gate", ok, text.strip().replace("\n", " ")[:120])
        except Exception as e:
            report("5a-save-gate", False, str(e))

        # 5b) 错误 token 直连桥必须被拒
        try:
            payload = {"token": "definitely-wrong-token", "tool": "ping", "args": {}}
            with socket.create_connection((HOST, PORT), timeout=10) as s:
                s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                buf = b""
                while b"\n" not in buf:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            resp = json.loads(buf.decode("utf-8"))
            report("5b-bad-token", resp.get("error") == "BAD_TOKEN", str(resp)[:120])
        except Exception as e:
            report("5b-bad-token", False, str(e))
    finally:
        pass
    return _finish(bridge, mcp, token_backup)


def _finish(bridge, mcp, token_backup):
    for proc in (mcp, bridge):
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
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
