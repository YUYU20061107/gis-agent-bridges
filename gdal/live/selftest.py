# -*- coding: utf-8 -*-
"""
selftest.py — GDAL/OGR 工具桥一键自检（纯标准库，无需 GDAL）

开发/自检机上没有 GDAL，因此本自检在临时目录里放四个假
二进制替身（gdalinfo / ogrinfo / gdal_translate / ogr2ogr，
按参数回放罐装输出，并把每次调用的 argv 与 GDAL_PAM_ENABLED
实际取值记进日志），经 GDAL_BRIDGE_* 环境变量注入桥，验证：
  1)  initialize        —— MCP 握手与 serverInfo（gdal-tool-bridge）
  2)  tools/list        —— 7 个 gdal_* 工具齐全
  3)  ping              —— 四件工具均可用、版本来自替身
  4)  discover          —— 格式枚举与政策口径如实
  5)  raster_info       —— -json 解析正确，且子进程 env 里
                           GDAL_PAM_ENABLED 确为 NO（防 .aux.xml）
  6)  vector_info       —— ogrinfo 文本解析：2 图层、要素数、
                           字段名正确
  7)  raster_stats      —— 波段统计解析正确（mean=12.5）
  8)  无 token          —— 不带 _token 必须被 BAD_TOKEN 拒绝
  9)  错误 token        —— 错误 _token 必须被 BAD_TOKEN 拒绝
  10) 转换缺 confirm    —— 必须被 CONFIRM_REQUIRED 拒绝，且
                           gdal_translate 一次都不能被调用
  11) 转换栅格正例      —— confirm 后落盘，argv 含 -of GTiff，
                           且不含任何 -co 透传
  12) 拒绝覆盖          —— 输出已存在必须被 OUTPUT_EXISTS 在
                           调用二进制前拒绝
  13) 非法格式          —— 枚举外 format 被 BAD_FORMAT 拒绝，
                           二进制不被调用
  14) 远程路径拒绝      —— https:// 输入被 REMOTE_PATH_REJECTED
                           在调用二进制前拒绝
  15) 转换矢量正例      —— ogr2ogr GeoJSON 落盘且可解析
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
口径声明：本自检只证明协议与参数校验成立（协议自检级），不证明
已在真实 GDAL 上可用；实机校准见 docs/CALIBRATION.md。
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
TEST_TOKEN = "gdal-selftest-token"

EXPECTED_TOOLS = {
    "gdal_ping", "gdal_discover", "gdal_raster_info",
    "gdal_vector_info", "gdal_raster_stats", "gdal_convert_raster",
    "gdal_convert_vector",
}

GDALINFO_SHIM = r'''#!/usr/bin/env python3
import json
import os
import sys

log = os.environ.get("FAKE_GDAL_LOG")
argv = sys.argv[1:]
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "gdalinfo", "argv": argv,
                            "pam": os.environ.get("GDAL_PAM_ENABLED")}) + "\n")
if argv and argv[0] == "--version":
    print("GDAL 3.9.0-fake, released 2024/01/01")
    sys.exit(0)
band = {"band": 1, "type": "Byte", "colorInterpretation": "Gray"}
if "-stats" in argv:
    band.update({"min": 0.0, "max": 255.0, "mean": 12.5, "stdDev": 3.25})
data = {"driverShortName": "GTiff", "driverLongName": "GeoTIFF",
        "size": [100, 50],
        "coordinateSystem": {"wkt": "GEOGCS[\"WGS 84\"]"},
        "geoTransform": [113.0, 0.01, 0.0, 21.0, 0.0, -0.01],
        "cornerCoordinates": {"upperLeft": [113.0, 21.0],
                              "lowerRight": [114.0, 20.5]},
        "bands": [band]}
print(json.dumps(data))
sys.exit(0)
'''

OGRINFO_SHIM = r'''#!/usr/bin/env python3
import json
import os
import sys

log = os.environ.get("FAKE_GDAL_LOG")
argv = sys.argv[1:]
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "ogrinfo", "argv": argv,
                            "pam": os.environ.get("GDAL_PAM_ENABLED")}) + "\n")
if argv and argv[0] == "--version":
    print("GDAL 3.9.0-fake, released 2024/01/01")
    sys.exit(0)
print("""INFO: Open of 'fake'
      using driver `GeoJSON' successful.

Layer name: roads
Geometry: Line String
Feature Count: 3
Extent: (113.0, 20.0) - (114.0, 21.0)
Layer SRS WKT:
(unknown)
id: Integer (0.0)
name: String (0.0)

Layer name: rivers
Geometry: Line String
Feature Count: 5
Extent: (113.1, 20.1) - (114.1, 21.1)
Layer SRS WKT:
(unknown)
name: String (0.0)
""")
sys.exit(0)
'''

TRANSLATE_SHIM = r'''#!/usr/bin/env python3
import json
import os
import sys

log = os.environ.get("FAKE_GDAL_LOG")
argv = sys.argv[1:]
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "gdal_translate", "argv": argv,
                            "pam": os.environ.get("GDAL_PAM_ENABLED")}) + "\n")
if argv and argv[0] == "--version":
    print("GDAL 3.9.0-fake, released 2024/01/01")
    sys.exit(0)
with open(argv[-1], "w", encoding="utf-8") as f:
    f.write("fake raster output")
print("fake translate done")
sys.exit(0)
'''

OGR2OGR_SHIM = r'''#!/usr/bin/env python3
import json
import os
import sys

log = os.environ.get("FAKE_GDAL_LOG")
argv = sys.argv[1:]
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "ogr2ogr", "argv": argv,
                            "pam": os.environ.get("GDAL_PAM_ENABLED")}) + "\n")
if argv and argv[0] == "--version":
    print("GDAL 3.9.0-fake, released 2024/01/01")
    sys.exit(0)
fmt = argv[argv.index("-f") + 1]
out = argv[argv.index("-f") + 2]
with open(out, "w", encoding="utf-8") as f:
    if fmt == "GeoJSON":
        f.write("{\"type\": \"FeatureCollection\", \"features\": []}")
    else:
        f.write("fake gpkg bytes")
print("fake ogr2ogr done")
sys.exit(0)
'''

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
    tmp = tempfile.mkdtemp(prefix="gdal-selftest-")
    bin_dir = os.path.join(tmp, "bin")
    home_dir = os.path.join(tmp, "home")
    work_dir = os.path.join(tmp, "work")
    for d in (bin_dir, home_dir, work_dir):
        os.makedirs(d)
    shims = {"gdalinfo": GDALINFO_SHIM, "ogrinfo": OGRINFO_SHIM,
             "gdal_translate": TRANSLATE_SHIM, "ogr2ogr": OGR2OGR_SHIM}
    paths = {}
    for name, src in shims.items():
        p = os.path.join(bin_dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
        os.chmod(p, 0o755)
        paths[name] = p
    shim_log = os.path.join(tmp, "gdal-invocations.log")
    raster_in = os.path.join(work_dir, "dem.tif")
    vector_in = os.path.join(work_dir, "roads.geojson")
    with open(raster_in, "wb") as f:
        f.write(b"fake tif bytes")
    with open(vector_in, "w", encoding="utf-8") as f:
        f.write('{"type": "FeatureCollection", "features": []}')

    def calls(tool=None):
        try:
            with open(shim_log, "r", encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]
        except Exception:
            rows = []
        if tool:
            rows = [r for r in rows if r["tool"] == tool]
        return rows

    env = dict(os.environ)
    env.update({
        "HOME": home_dir,
        "GDAL_BRIDGE_TOKEN": TEST_TOKEN,
        "GDAL_BRIDGE_GDALINFO": paths["gdalinfo"],
        "GDAL_BRIDGE_OGRINFO": paths["ogrinfo"],
        "GDAL_BRIDGE_GDAL_TRANSLATE": paths["gdal_translate"],
        "GDAL_BRIDGE_OGR2OGR": paths["ogr2ogr"],
        "FAKE_GDAL_LOG": shim_log,
        # 故意在父环境里放开 PAM，验证桥会强制关掉再传给子进程
        "GDAL_PAM_ENABLED": "YES",
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
            ok = info.get("name") == "gdal-tool-bridge" and \
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
            data, is_err = tool_json(client.call_tool("gdal_ping"))
            ok = (not is_err) and data and data.get("pong") is True and \
                data.get("gdalinfo_available") is True and \
                data.get("ogrinfo_available") is True
            report("3-ping", ok, json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("3-ping", False, str(e))

        # 4) discover
        try:
            data, is_err = tool_json(client.call_tool("gdal_discover"))
            tools = (data.get("tools") or {}) if data else {}
            ok = (not is_err) and data and \
                set((data.get("raster_formats") or {}).keys()) == \
                {"GTiff", "PNG", "JPEG"} and \
                tools.get("gdalinfo", {}).get("version", "").startswith(
                    "GDAL 3.9.0-fake")
            report("4-discover", ok, json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("4-discover", False, str(e))

        # 5) raster_info + PAM 断言
        try:
            data, is_err = tool_json(client.call_tool(
                "gdal_raster_info", {"path": raster_in}))
            gdalinfo_calls = [c for c in calls("gdalinfo")
                              if "-json" in c["argv"]]
            pam_ok = bool(gdalinfo_calls) and \
                all(c["pam"] == "NO" for c in gdalinfo_calls)
            ok = (not is_err) and data and \
                (data.get("driver") or {}).get("short_name") == "GTiff" and \
                data.get("size") == [100, 50] and data.get("bands") == 1 and \
                pam_ok
            report("5-raster-info-pam", ok,
                   json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("5-raster-info-pam", False, str(e))

        # 6) vector_info
        try:
            data, is_err = tool_json(client.call_tool(
                "gdal_vector_info", {"path": vector_in}))
            layers = (data.get("layers") or []) if data else []
            roads = next((l for l in layers if l["name"] == "roads"), {})
            ok = (not is_err) and data and data.get("layer_count") == 2 and \
                roads.get("feature_count") == 3 and \
                roads.get("fields") == ["id", "name"] and \
                roads.get("extent") == [113.0, 20.0, 114.0, 21.0]
            report("6-vector-info", ok,
                   json.dumps(data, ensure_ascii=False)[:180])
        except Exception as e:
            report("6-vector-info", False, str(e))

        # 7) raster_stats
        try:
            data, is_err = tool_json(client.call_tool(
                "gdal_raster_stats", {"path": raster_in}))
            bands = (data.get("bands") or []) if data else []
            ok = (not is_err) and data and len(bands) == 1 and \
                bands[0].get("mean") == 12.5 and \
                bands[0].get("std_dev") == 3.25
            report("7-raster-stats", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("7-raster-stats", False, str(e))

        # 8) 无 token 必须 BAD_TOKEN
        try:
            text, is_err = tool_text(client.call_tool("gdal_ping", token=None))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("8-no-token", ok, text.strip()[:120])
        except Exception as e:
            report("8-no-token", False, str(e))

        # 9) 错误 token 必须 BAD_TOKEN
        try:
            text, is_err = tool_text(client.call_tool(
                "gdal_ping", token="definitely-wrong-token"))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("9-bad-token", ok, text.strip()[:120])
        except Exception as e:
            report("9-bad-token", False, str(e))

        # 10) 转换缺 confirm：闸在执行前，二进制不被调用
        raster_out = os.path.join(work_dir, "dem_copy.tif")
        try:
            before = len(calls("gdal_translate"))
            data, _e = tool_json(client.call_tool(
                "gdal_convert_raster",
                {"path": raster_in, "output": raster_out,
                 "format": "GTiff"}))
            ok = data and data.get("error_code") == "CONFIRM_REQUIRED" and \
                len(calls("gdal_translate")) == before and \
                not os.path.exists(raster_out)
            report("10-convert-no-confirm", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("10-convert-no-confirm", False, str(e))

        # 11) 转换栅格正例：落盘、argv 含 -of GTiff、无 -co
        try:
            before = len(calls("gdal_translate"))
            data, is_err = tool_json(client.call_tool(
                "gdal_convert_raster",
                {"path": raster_in, "output": raster_out,
                 "format": "GTiff", "confirm": True}))
            rows = calls("gdal_translate")
            new_argv = rows[-1]["argv"] if len(rows) > before else []
            flat = " ".join(new_argv)
            ok = (not is_err) and data and data.get("executed") is True and \
                os.path.isfile(raster_out) and \
                "-of GTiff" in flat and "-co" not in flat
            report("11-convert-raster-ok", ok,
                   json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("11-convert-raster-ok", False, str(e))

        # 12) 拒绝覆盖已存在输出（二进制不被调用）
        try:
            before = len(calls("gdal_translate"))
            data, _e = tool_json(client.call_tool(
                "gdal_convert_raster",
                {"path": raster_in, "output": raster_out,
                 "format": "GTiff", "confirm": True}))
            ok = data and data.get("error_code") == "OUTPUT_EXISTS" and \
                len(calls("gdal_translate")) == before
            report("12-convert-exists", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("12-convert-exists", False, str(e))

        # 13) 非法格式被拒（二进制不被调用）
        try:
            before = len(calls("gdal_translate"))
            data, _e = tool_json(client.call_tool(
                "gdal_convert_raster",
                {"path": raster_in,
                 "output": os.path.join(work_dir, "x.nc"),
                 "format": "netCDF", "confirm": True}))
            ok = data and data.get("error_code") == "BAD_FORMAT" and \
                len(calls("gdal_translate")) == before
            report("13-bad-format", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("13-bad-format", False, str(e))

        # 14) 远程路径在调用前被拒
        try:
            before = len(calls("gdalinfo"))
            data, _e = tool_json(client.call_tool(
                "gdal_raster_info",
                {"path": "https://example.com/dem.tif"}))
            ok = data and \
                data.get("error_code") == "REMOTE_PATH_REJECTED" and \
                len(calls("gdalinfo")) == before
            report("14-remote-rejected", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("14-remote-rejected", False, str(e))

        # 15) 转换矢量正例
        vector_out = os.path.join(work_dir, "roads_out.geojson")
        try:
            data, is_err = tool_json(client.call_tool(
                "gdal_convert_vector",
                {"path": vector_in, "output": vector_out,
                 "format": "GeoJSON", "confirm": True}))
            file_ok = False
            if os.path.isfile(vector_out):
                with open(vector_out, "r", encoding="utf-8") as f:
                    gj = json.load(f)
                file_ok = gj.get("type") == "FeatureCollection"
            ok = (not is_err) and data and data.get("executed") is True and \
                file_ok
            report("15-convert-vector-ok", ok,
                   json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("15-convert-vector-ok", False, str(e))
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
