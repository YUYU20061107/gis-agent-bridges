# -*- coding: utf-8 -*-
"""
selftest.py — PostGIS 消费侧桥一键自检（纯标准库，无需 PostgreSQL）

开发/自检机上没有 PostgreSQL+PostGIS，因此本自检用一个假 psql 替身
（shim：临时目录里的小程序，按 SQL 关键词回放罐装输出，并把每次被
调用记进日志文件）验证协议与安全闸，检查：
  1) initialize        —— MCP 握手与 serverInfo（postgis-consumer-bridge）
  2) tools/list        —— 6 个 postgis_* 工具齐全（全部只读，无写库工具）
  3) tools/call ping   —— 拿到 pong
  4) discover          —— 探针 SELECT 1 与 PostGIS 版本经替身通过、
                          allowed_tables 与连接环境状态如实
  5) 无 token          —— 不带 _token 的调用必须被 BAD_TOKEN 拒绝
  6) 错误 token        —— 错误 _token 必须被 BAD_TOKEN 拒绝
  7) 非法表名          —— "parcels; DROP TABLE parcels" 必须被
                          BAD_TABLE_NAME 拒绝，且假 psql 一次都不能被
                          调用（校验在查库前）
  8) 表不在允许集合    —— 标识符合法但未配置的表必须被
                          TABLE_NOT_ALLOWED 拒绝，且假 psql 不被调用
  9) 几何列清单正例    —— parcels 的几何列被正确解析（geom/POINT/4326）
  10) 属性列正例       —— 3 个属性列与替身罐装一致
  11) summary 正例     —— 行数 42、范围四值与替身罐装一致
  12) export 正例      —— GeoJSON 文件真实落盘、可解析、2 个 feature
  13) export 路径穿越  —— filename "../evil.geojson" 必须被
                          BAD_FILENAME 拒绝，且导出目录外不得出现该文件
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
口径声明：本自检只证明协议与参数校验成立（协议自检级），不证明已在
真实 PostgreSQL+PostGIS 上可用；实机校准见 docs/CALIBRATION.md。
自检把 HOME 指到临时目录，桥的运行日志与 token 文件都留在临时目录内。
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
TEST_TOKEN = "postgis-selftest-token"

EXPECTED_TOOLS = {
    "postgis_ping", "postgis_discover", "postgis_list_spatial_tables",
    "postgis_table_columns", "postgis_table_summary",
    "postgis_export_geojson",
}

SHIM_SOURCE = '''#!/usr/bin/env python3
# 假 psql 替身：按 -c 的 SQL 关键词回放罐装输出，并记录每次调用。
import os
import sys

log = os.environ.get("FAKE_PSQL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write("invoked\\n")
args = sys.argv[1:]
sql = ""
if "-c" in args:
    sql = args[args.index("-c") + 1]
if "--version" in args:
    print("psql (PostgreSQL) 0.0.0-fake-shim")
elif "ST_AsGeoJSON" in sql:
    print('{"type": "FeatureCollection", "features": ['
          '{"type": "Feature", "geometry": {"type": "Point", '
          '"coordinates": [0.0, 0.0]}, "properties": {"id": 1}}, '
          '{"type": "Feature", "geometry": {"type": "Point", '
          '"coordinates": [1.0, 1.0]}, "properties": {"id": 2}}]}')
elif "ST_Extent" in sql:
    print("-10.5\\t-20.25\\t30.0\\t40.75")
elif "PostGIS_Version" in sql:
    print("3.5 USE_GEOS=1 USE_PROJ=1 USE_STATS=1")
elif "geometry_columns" in sql:
    print("geom\\tPOINT\\t4326")
elif "information_schema.columns" in sql:
    print("id\\tinteger")
    print("name\\ttext")
    print("geom\\tUSER-DEFINED")
elif "count(*)" in sql:
    print("42")
elif "SELECT 1" in sql:
    print("1")
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
    tmp = tempfile.mkdtemp(prefix="postgis-selftest-")
    bin_dir = os.path.join(tmp, "bin")
    export_dir = os.path.join(tmp, "exports")
    home_dir = os.path.join(tmp, "home")
    for d in (bin_dir, export_dir, home_dir):
        os.makedirs(d)
    shim = os.path.join(bin_dir, "psql")
    with open(shim, "w", encoding="utf-8") as f:
        f.write(SHIM_SOURCE)
    os.chmod(shim, 0o755)
    shim_log = os.path.join(tmp, "psql-invocations.log")

    def shim_calls():
        try:
            with open(shim_log, "r", encoding="utf-8") as f:
                return len(f.read().splitlines())
        except Exception:
            return 0

    env = dict(os.environ)
    env.update({
        "HOME": home_dir,
        "POSTGIS_BRIDGE_TOKEN": TEST_TOKEN,
        "POSTGIS_PSQL": shim,
        "POSTGIS_ALLOWED_TABLES": "parcels",
        "POSTGIS_EXPORT_DIR": export_dir,
        "FAKE_PSQL_LOG": shim_log,
        "PGHOST": "localhost", "PGDATABASE": "fakedb", "PGUSER": "fakeuser",
    })
    env.pop("PGPASSWORD", None)
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
            ok = info.get("name") == "postgis-consumer-bridge" and \
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
            data, is_err = tool_json(client.call_tool("postgis_ping"))
            ok = (not is_err) and data and data.get("pong") is True and \
                data.get("psql_available") is True
            report("3-ping", ok, json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("3-ping", False, str(e))

        # 4) discover（探针与版本经替身通过；密码只报未设置）
        try:
            data, is_err = tool_json(client.call_tool("postgis_discover"))
            ok = (not is_err) and data and \
                (data.get("probe_select1") or {}).get("ok") is True and \
                (data.get("postgis_version") or {}).get("ok") is True and \
                str((data.get("postgis_version") or {}).get("raw", "")).startswith("3.5") and \
                data.get("allowed_tables") == ["parcels"] and \
                (data.get("connection_env") or {}).get("PGPASSWORD_set") is False
            report("4-discover", ok, json.dumps(data, ensure_ascii=False)[:180])
        except Exception as e:
            report("4-discover", False, str(e))

        # 5) 无 token 必须 BAD_TOKEN
        try:
            text, is_err = tool_text(client.call_tool(
                "postgis_ping", token=None))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("5-no-token", ok, text.strip()[:120])
        except Exception as e:
            report("5-no-token", False, str(e))

        # 6) 错误 token 必须 BAD_TOKEN
        try:
            text, is_err = tool_text(client.call_tool(
                "postgis_ping", token="definitely-wrong-token"))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("6-bad-token", ok, text.strip()[:120])
        except Exception as e:
            report("6-bad-token", False, str(e))

        # 7) 非法表名在查库前被拒，替身不被调用
        try:
            before = shim_calls()
            data, _e = tool_json(client.call_tool(
                "postgis_table_summary",
                {"table": "parcels; DROP TABLE parcels"}))
            ok = data and data.get("error_code") == "BAD_TABLE_NAME" and \
                shim_calls() == before
            report("7-bad-table-name", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("7-bad-table-name", False, str(e))

        # 8) 表不在允许集合被拒，替身不被调用
        try:
            before = shim_calls()
            data, _e = tool_json(client.call_tool(
                "postgis_table_columns", {"table": "other_table"}))
            ok = data and data.get("error_code") == "TABLE_NOT_ALLOWED" and \
                shim_calls() == before
            report("8-table-not-allowed", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("8-table-not-allowed", False, str(e))

        # 9) 几何列清单正例
        try:
            data, is_err = tool_json(client.call_tool(
                "postgis_list_spatial_tables"))
            tbl = (data.get("tables") or [{}])[0] if data else {}
            cols = tbl.get("geometry_columns") or []
            ok = (not is_err) and data and tbl.get("table") == "parcels" and \
                tbl.get("is_spatial") is True and len(cols) == 1 and \
                cols[0]["column"] == "geom" and cols[0]["type"] == "POINT" and \
                cols[0]["srid"] == 4326
            report("9-list-spatial", ok, json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("9-list-spatial", False, str(e))

        # 10) 属性列正例
        try:
            data, is_err = tool_json(client.call_tool(
                "postgis_table_columns", {"table": "parcels"}))
            names = [c["name"] for c in (data.get("columns") or [])] if data else []
            ok = (not is_err) and data and names == ["id", "name", "geom"]
            report("10-columns-ok", ok, json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("10-columns-ok", False, str(e))

        # 11) summary 正例
        try:
            data, is_err = tool_json(client.call_tool(
                "postgis_table_summary", {"table": "parcels"}))
            ext = (data.get("extent") or {}) if data else {}
            ok = (not is_err) and data and data.get("row_count") == 42 and \
                data.get("geom") == "geom" and \
                ext.get("xmin") == -10.5 and ext.get("ymin") == -20.25 and \
                ext.get("xmax") == 30.0 and ext.get("ymax") == 40.75
            report("11-summary-ok", ok, json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("11-summary-ok", False, str(e))

        # 12) export 正例：文件落盘且可解析
        export_path = os.path.join(export_dir, "parcels_sample.geojson")
        try:
            data, is_err = tool_json(client.call_tool(
                "postgis_export_geojson",
                {"table": "parcels", "filename": "parcels_sample.geojson",
                 "limit": 2}))
            file_ok = False
            if os.path.isfile(export_path):
                with open(export_path, "r", encoding="utf-8") as f:
                    gj = json.load(f)
                file_ok = gj.get("type") == "FeatureCollection" and \
                    len(gj.get("features") or []) == 2
            ok = (not is_err) and data and data.get("features") == 2 and \
                data.get("path") == export_path and file_ok
            report("12-export-ok", ok, json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("12-export-ok", False, str(e))

        # 13) export 路径穿越被拒
        try:
            data, _e = tool_json(client.call_tool(
                "postgis_export_geojson",
                {"table": "parcels", "filename": "../evil.geojson"}))
            ok = data and data.get("error_code") == "BAD_FILENAME" and \
                not os.path.exists(os.path.join(tmp, "evil.geojson"))
            report("13-export-traversal", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("13-export-traversal", False, str(e))
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
