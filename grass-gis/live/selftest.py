# -*- coding: utf-8 -*-
"""
selftest.py — GRASS GIS 无头桥一键自检（纯标准库，无需 GRASS）

开发/自检机上没有 GRASS GIS，因此本自检用一个假 grass 替身
（shim：临时目录里的小程序，按 --exec 后的模块名回放罐装输出，
并把每次被调用的 argv 记进日志文件）加上一个纯文件搭出来的假
location，验证协议与安全闸，检查：
  1)  initialize        —— MCP 握手与 serverInfo（grass-headless-bridge）
  2)  tools/list        —— 7 个 grass_* 工具齐全
  3)  ping              —— 经替身拿到版本与可用性
  4)  discover          —— gisdbase 与 location 清单如实
  5)  location_info     —— PROJ_INFO / WIND 被正确解析（纯文件读）
  6)  list_maps 正例    —— 替身罐装的 2 张栅格名解析正确
  7)  raster_info 正例  —— r.info 键值解析正确（cells=10000）
  8)  无 token          —— 不带 _token 的调用必须被 BAD_TOKEN 拒绝
  9)  错误 token        —— 错误 _token 必须被 BAD_TOKEN 拒绝
  10) run 缺 confirm    —— 必须被 CONFIRM_REQUIRED 拒绝，且替身
                           一次都不能被调用（闸在执行前）
  11) run 正例          —— confirm 后作业执行，argv 含固定模块
                           r.slope.aspect 且绝无 --overwrite
  12) run 非法作业      —— 枚举外 job 必须被 BAD_JOB 拒绝，替身
                           不被调用
  13) export 闸与落盘   —— 无 confirm 被拒；confirm 后 GeoJSON
                           真实落盘且可解析
  14) export 拒绝覆盖   —— 输出路径已存在必须被 OUTPUT_EXISTS
                           在调用 GRASS 前拒绝
  15) 非法图层名        —— "x;rm" 必须被 BAD_MAP_NAME 拒绝，
                           替身不被调用
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
口径声明：本自检只证明协议与参数校验成立（协议自检级），不证明
已在真实 GRASS GIS 上可用；实机校准见 docs/CALIBRATION.md。
自检把 HOME 指到临时目录，桥的运行日志与 token 文件都留在临时
目录内。
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_PY = os.path.join(HERE, "mcp_server.py")
TEST_TOKEN = "grass-selftest-token"

EXPECTED_TOOLS = {
    "grass_ping", "grass_discover", "grass_location_info",
    "grass_list_maps", "grass_raster_info", "grass_run_module",
    "grass_export_vector",
}

SHIM_SOURCE = '''#!/usr/bin/env python3
# 假 grass 替身：按 --exec 后的模块名回放罐装输出，并记录每次调用。
import json
import os
import sys

log = os.environ.get("FAKE_GRASS_LOG")
argv = sys.argv[1:]
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(argv) + "\\n")
if argv and argv[0] == "--version":
    print("GRASS GIS 8.4.0-fake")
    sys.exit(0)
if "--exec" not in argv:
    sys.exit(2)
rest = argv[argv.index("--exec") + 1:]
module = rest[0] if rest else ""
kv = {}
for a in rest[1:]:
    if "=" in a:
        k, v = a.split("=", 1)
        kv[k] = v
if module == "g.list":
    if kv.get("type") == "raster":
        print("elevation")
        print("slope")
    elif kv.get("type") == "vector":
        print("roads")
        print("rivers")
elif module == "r.info":
    print("n=21.0")
    print("s=20.0")
    print("e=114.0")
    print("w=113.0")
    print("rows=100")
    print("cols=100")
    print("cells=10000")
    print("min=0")
    print("max=255")
elif module in ("r.slope.aspect", "r.relief", "r.resample"):
    print("fake module done")
elif module == "v.out.ogr":
    with open(kv["output"], "w", encoding="utf-8") as f:
        f.write("{\\"type\\": \\"FeatureCollection\\", \\"features\\": []}")
    print("fake export done")
sys.exit(0)
'''

PROJ_INFO = """name: WGS 84
datum: wgs84
ellipsoid: wgs84
proj: ll
"""

WIND = """proj: 3
zone: 0
north: 21.0
south: 20.0
east: 114.0
west: 113.0
cols: 100
rows: 100
e-w resol: 0.01
n-s resol: 0.01
"""

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""), flush=True)


class _LineReader:
    """逐行读取子进程 stdout（线程+队列，跨平台；迁移自仓内自检口径）。"""

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
        except Exception as e:
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


def tool_json(resp):
    text, is_err = tool_text(resp)
    try:
        return json.loads(text), is_err
    except Exception:
        return None, is_err


def main():
    tmp = tempfile.mkdtemp(prefix="grass-selftest-")
    bin_dir = os.path.join(tmp, "bin")
    home_dir = os.path.join(tmp, "home")
    gisdbase = os.path.join(tmp, "gisdbase")
    export_dir = os.path.join(tmp, "exports")
    permanent = os.path.join(gisdbase, "demo", "PERMANENT")
    mapset = os.path.join(gisdbase, "demo", "user1")
    for d in (bin_dir, home_dir, permanent, mapset, export_dir):
        os.makedirs(d)
    with open(os.path.join(permanent, "PROJ_INFO"), "w",
              encoding="utf-8") as f:
        f.write(PROJ_INFO)
    with open(os.path.join(permanent, "WIND"), "w", encoding="utf-8") as f:
        f.write(WIND)
    shim = os.path.join(bin_dir, "grass")
    with open(shim, "w", encoding="utf-8") as f:
        f.write(SHIM_SOURCE)
    os.chmod(shim, 0o755)
    shim_log = os.path.join(tmp, "grass-invocations.log")

    def shim_calls():
        try:
            with open(shim_log, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except Exception:
            return []

    env = dict(os.environ)
    env.update({
        "HOME": home_dir,
        "GRASS_BRIDGE_TOKEN": TEST_TOKEN,
        "GRASS_BRIDGE_BIN": shim,
        "GRASS_BRIDGE_GISDBASE": gisdbase,
        "GRASS_BRIDGE_EXPORT_DIR": export_dir,
        "FAKE_GRASS_LOG": shim_log,
    })
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
            ok = info.get("name") == "grass-headless-bridge" and \
                str(info.get("version", "")).startswith("0.1")
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
            data, is_err = tool_json(client.call_tool("grass_ping"))
            ok = (not is_err) and data and data.get("pong") is True and \
                data.get("grass_available") is True and \
                "8.4.0-fake" in (data.get("grass_version") or "")
            report("3-ping", ok, json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("3-ping", False, str(e))

        # 4) discover
        try:
            data, is_err = tool_json(client.call_tool("grass_discover"))
            ok = (not is_err) and data and \
                data.get("locations") == ["demo"] and \
                set(data.get("run_jobs") or []) == \
                {"slope_aspect", "hillshade", "resample_nearest"}
            report("4-discover", ok, json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("4-discover", False, str(e))

        # 5) location_info
        try:
            data, is_err = tool_json(client.call_tool(
                "grass_location_info", {"location": "demo"}))
            proj = (data.get("projection") or {}) if data else {}
            wind = (data.get("default_region") or {}) if data else {}
            ok = (not is_err) and data and proj.get("name") == "WGS 84" and \
                wind.get("north") == "21.0" and \
                set(data.get("mapsets") or []) == {"PERMANENT", "user1"}
            report("5-location-info", ok,
                   json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("5-location-info", False, str(e))

        # 6) list_maps 正例
        try:
            data, is_err = tool_json(client.call_tool(
                "grass_list_maps",
                {"location": "demo", "mapset": "user1", "type": "raster"}))
            ok = (not is_err) and data and \
                data.get("maps") == ["elevation", "slope"] and \
                data.get("count") == 2
            report("6-list-maps", ok, json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("6-list-maps", False, str(e))

        # 7) raster_info 正例
        try:
            data, is_err = tool_json(client.call_tool(
                "grass_raster_info",
                {"location": "demo", "mapset": "user1", "map": "elevation"}))
            info = (data.get("info") or {}) if data else {}
            ok = (not is_err) and data and info.get("cells") == "10000" and \
                info.get("max") == "255"
            report("7-raster-info", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("7-raster-info", False, str(e))

        # 8) 无 token 必须 BAD_TOKEN
        try:
            text, is_err = tool_text(client.call_tool(
                "grass_ping", token=None))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("8-no-token", ok, text.strip()[:120])
        except Exception as e:
            report("8-no-token", False, str(e))

        # 9) 错误 token 必须 BAD_TOKEN
        try:
            text, is_err = tool_text(client.call_tool(
                "grass_ping", token="definitely-wrong-token"))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("9-bad-token", ok, text.strip()[:120])
        except Exception as e:
            report("9-bad-token", False, str(e))

        # 10) run 缺 confirm：闸在执行前，替身不被调用
        try:
            before = len(shim_calls())
            data, _e = tool_json(client.call_tool(
                "grass_run_module",
                {"location": "demo", "mapset": "user1",
                 "job": "slope_aspect",
                 "params": {"elevation": "elevation", "slope": "slope_new",
                            "aspect": "aspect_new"}}))
            ok = data and data.get("error_code") == "CONFIRM_REQUIRED" and \
                len(shim_calls()) == before
            report("10-run-no-confirm", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("10-run-no-confirm", False, str(e))

        # 11) run 正例：模块固定、无 --overwrite
        try:
            before = len(shim_calls())
            data, is_err = tool_json(client.call_tool(
                "grass_run_module",
                {"location": "demo", "mapset": "user1",
                 "job": "slope_aspect", "confirm": True,
                 "params": {"elevation": "elevation", "slope": "slope_new",
                            "aspect": "aspect_new"}}))
            calls = shim_calls()
            new_argv = calls[-1] if len(calls) > before else []
            flat = " ".join(new_argv)
            ok = (not is_err) and data and data.get("executed") is True and \
                data.get("module") == "r.slope.aspect" and \
                "r.slope.aspect" in flat and "--overwrite" not in flat and \
                data.get("overwrite_used") is False
            report("11-run-ok", ok, json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("11-run-ok", False, str(e))

        # 12) 枚举外 job 被拒，替身不被调用
        try:
            before = len(shim_calls())
            data, _e = tool_json(client.call_tool(
                "grass_run_module",
                {"location": "demo", "mapset": "user1",
                 "job": "r.univar", "confirm": True,
                 "params": {"map": "elevation"}}))
            ok = data and data.get("error_code") == "BAD_JOB" and \
                len(shim_calls()) == before
            report("12-run-bad-job", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("12-run-bad-job", False, str(e))

        # 13) export：无 confirm 被拒；confirm 后落盘
        export_path = os.path.join(export_dir, "roads.geojson")
        try:
            data0, _e0 = tool_json(client.call_tool(
                "grass_export_vector",
                {"location": "demo", "mapset": "user1", "map": "roads",
                 "output": export_path}))
            gate_ok = data0 and \
                data0.get("error_code") == "CONFIRM_REQUIRED" and \
                not os.path.exists(export_path)
            data, is_err = tool_json(client.call_tool(
                "grass_export_vector",
                {"location": "demo", "mapset": "user1", "map": "roads",
                 "output": export_path, "confirm": True}))
            file_ok = False
            if os.path.isfile(export_path):
                with open(export_path, "r", encoding="utf-8") as f:
                    gj = json.load(f)
                file_ok = gj.get("type") == "FeatureCollection"
            ok = gate_ok and (not is_err) and data and \
                data.get("bytes", 0) > 0 and file_ok
            report("13-export-ok", ok,
                   json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("13-export-ok", False, str(e))

        # 14) export 拒绝覆盖已存在文件（调用 GRASS 前）
        try:
            before = len(shim_calls())
            data, _e = tool_json(client.call_tool(
                "grass_export_vector",
                {"location": "demo", "mapset": "user1", "map": "roads",
                 "output": export_path, "confirm": True}))
            ok = data and data.get("error_code") == "OUTPUT_EXISTS" and \
                len(shim_calls()) == before
            report("14-export-exists", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("14-export-exists", False, str(e))

        # 15) 非法图层名在执行前被拒
        try:
            before = len(shim_calls())
            data, _e = tool_json(client.call_tool(
                "grass_raster_info",
                {"location": "demo", "mapset": "user1", "map": "x;rm"}))
            ok = data and data.get("error_code") == "BAD_MAP_NAME" and \
                len(shim_calls()) == before
            report("15-bad-map-name", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("15-bad-map-name", False, str(e))
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
