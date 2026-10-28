# -*- coding: utf-8 -*-
"""
selftest.py — istSOS 消费侧只读桥一键自检（纯标准库，无需任何真实服务）

自检在本机 127.0.0.1 随机端口起一个“假 STA 服务端”（只回放固定 JSON），
再启动 live/mcp_server.py 子进程对着它跑，自动检查：
  1)  initialize        —— MCP 握手与 serverInfo（istsos-consumer-bridge 0.1.x）
  2)  tools/list        —— 6 个 istsos_* 只读工具齐全、无多余
  3)  ping              —— 经假服务端根路径确认 server_reachable=true
  4)  list_things       —— 回放的 2 个 Things 数量对得上
  5)  list_datastreams  —— thing_id=1 时只回该 Thing 的 1 条流
  6)  get_observations  —— limit=2 时只回 2 条观测
  7)  limit 超限        —— limit=101 必须以 LIMIT_EXCEEDED 被拒（不许静默截断）
  8)  无 token          —— 不带 _token 的调用必须被 BAD_TOKEN 拒绝
  9)  错 token          —— 错误 _token 必须被 BAD_TOKEN 拒绝
  10) export            —— 导出 GeoJSON 真实落盘：FeatureCollection、3 个
                           Feature、几何与假 Location 坐标一致、result 对得上
  11) 只读纪律          —— 假服务端收到的请求必须全部是 GET
  12) 未配置诚实性      —— 另起一个不带 ISTSOS_BASE_URL 的服务端进程，
                           list_things 必须报 NOT_CONFIGURED、不许编造数据
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。

注意口径：本自检只证明“桥对着一个回放固定 JSON 的假 STA 服务端时，
协议与参数校验行为正确”，属于协议级自检。**istSOS4 本体未实测**，
自检通过不等于任何真实 STA 服务端已验证，见 docs/CALIBRATION.md。
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_PY = os.path.join(HERE, "mcp_server.py")
TEST_TOKEN = "istsos-selftest-token"

EXPECTED_TOOLS = {
    "istsos_ping", "istsos_discover", "istsos_list_things",
    "istsos_list_datastreams", "istsos_get_observations",
    "istsos_export_observations_geojson",
}

RESULTS = []
REQUESTS = []  # 假服务端收到的 (method, path)

FAKE_LOCATION = {"type": "Point", "coordinates": [8.961, 46.003]}
FAKE_OBSERVATIONS = [
    {"@iot.id": 101, "phenomenonTime": "2026-01-03T00:00:00.000Z",
     "result": 23.1, "resultTime": "2026-01-03T00:00:01.000Z"},
    {"@iot.id": 102, "phenomenonTime": "2026-01-02T00:00:00.000Z",
     "result": 22.4, "resultTime": "2026-01-02T00:00:01.000Z"},
    {"@iot.id": 103, "phenomenonTime": "2026-01-01T00:00:00.000Z",
     "result": 21.5, "resultTime": "2026-01-01T00:00:01.000Z"},
]


def _collection(value):
    return {"@iot.count": len(value), "value": value}


def fake_sta_response(path, query):
    """按 STA 1.1 的基本形状回放固定 JSON；认 $top，其余查询参数忽略。"""
    top = None
    if "$top" in query:
        try:
            top = int(query["$top"][0])
        except Exception:
            top = None

    def cut(v):
        return v[:top] if top is not None else v

    if path in ("/v1.1", "/v1.1/"):
        return {"value": [{"name": "Things", "url": "http://x/v1.1/Things"},
                          {"name": "Datastreams",
                           "url": "http://x/v1.1/Datastreams"},
                          {"name": "Observations",
                           "url": "http://x/v1.1/Observations"}]}
    if path == "/v1.1/Things":
        return _collection(cut([
            {"@iot.id": 1, "name": "WeatherStation-1",
             "description": "fake rooftop weather station"},
            {"@iot.id": 2, "name": "RiverGauge-1",
             "description": "fake river level gauge"}]))
    if path == "/v1.1/Datastreams":
        return _collection(cut([
            {"@iot.id": 1, "name": "AirTemperature",
             "description": "fake air temperature",
             "unitOfMeasurement": {"name": "degree Celsius",
                                   "symbol": "degC",
                                   "definition": "http://unitsofmeasure.org"}},
            {"@iot.id": 2, "name": "WaterLevel",
             "description": "fake water level",
             "unitOfMeasurement": {"name": "metre", "symbol": "m",
                                   "definition": "http://unitsofmeasure.org"}}]))
    if path == "/v1.1/Things(1)/Datastreams":
        return _collection(cut([
            {"@iot.id": 1, "name": "AirTemperature",
             "description": "fake air temperature",
             "unitOfMeasurement": {"name": "degree Celsius",
                                   "symbol": "degC",
                                   "definition": "http://unitsofmeasure.org"}}]))
    if path == "/v1.1/Datastreams(1)":
        return {"@iot.id": 1, "name": "AirTemperature",
                "Thing": {"@iot.id": 1},
                "Thing@iot.navigationLink": "Datastreams(1)/Thing"}
    if path == "/v1.1/Things(1)/Locations":
        return _collection([
            {"@iot.id": 1, "name": "Rooftop",
             "location": FAKE_LOCATION,
             "encodingType": "application/vnd.geo+json"}])
    if path == "/v1.1/Datastreams(1)/Observations":
        return _collection(cut(list(FAKE_OBSERVATIONS)))
    return None


class FakeStaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _record_and_reply(self, method):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        REQUESTS.append((method, parsed.path))
        if method != "GET":
            body = json.dumps({"error": {"message": "GET only"}}).encode()
            self.send_response(405)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data = fake_sta_response(parsed.path, query)
        if data is None:
            body = json.dumps({"error": {"message": "not found"}}).encode()
            self.send_response(404)
        else:
            body = json.dumps(data).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._record_and_reply("GET")

    def do_POST(self):
        self._record_and_reply("POST")

    def do_PUT(self):
        self._record_and_reply("PUT")

    def do_PATCH(self):
        self._record_and_reply("PATCH")

    def do_DELETE(self):
        self._record_and_reply("DELETE")


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""), flush=True)


class _LineReader:
    """逐行读取子进程 stdout（后台线程 + 队列，与 fme/selftest 同口径；
    Windows 上 select() 不能等管道句柄）。"""

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


def start_mcp(env_extra):
    env = dict(os.environ)
    env.pop("ISTSOS_BASE_URL", None)
    env.update(env_extra)
    proc = subprocess.Popen([sys.executable, MCP_PY], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    return proc


def stop_mcp(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def init_client(proc, token=TEST_TOKEN):
    client = McpClient(proc, token)
    resp = client.request("initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "selftest", "version": "0"}})
    info = (resp.get("result") or {}).get("serverInfo") or {}
    client.notify("notifications/initialized")
    return client, info


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStaHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/v1.1" % port
    out_dir = tempfile.mkdtemp(prefix="istsos-selftest-")

    proc = start_mcp({"ISTSOS_BASE_URL": base,
                      "ISTSOS_BRIDGE_TOKEN": TEST_TOKEN,
                      "ISTSOS_BRIDGE_OUTPUT_DIR": out_dir})
    client = None
    try:
        # 1) initialize
        try:
            client, info = init_client(proc)
            ok = info.get("name") == "istsos-consumer-bridge" and \
                str(info.get("version", "")).startswith("0.1")
            report("1-initialize", ok, "serverInfo=%s" % info)
        except Exception as e:
            report("1-initialize", False, str(e))

        if client is not None:
            # 2) tools/list
            try:
                resp = client.request("tools/list")
                names = {t["name"] for t in
                         (resp.get("result") or {}).get("tools", [])}
                missing = EXPECTED_TOOLS - names
                extra = names - EXPECTED_TOOLS
                report("2-tools-list", not missing and not extra,
                       "共 %d 个工具%s%s" % (
                           len(names),
                           ("，缺: %s" % sorted(missing)) if missing else "",
                           ("，多: %s" % sorted(extra)) if extra else ""))
            except Exception as e:
                report("2-tools-list", False, str(e))

            # 3) ping
            try:
                data, is_err = tool_json(client.call_tool("istsos_ping"))
                ok = (not is_err) and data and data.get("pong") and \
                    data.get("server_reachable") is True
                report("3-ping", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("3-ping", False, str(e))

            # 4) list_things
            try:
                data, is_err = tool_json(client.call_tool("istsos_list_things"))
                ok = (not is_err) and data and data.get("count") == 2
                report("4-list-things", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("4-list-things", False, str(e))

            # 5) list_datastreams thing_id=1
            try:
                data, is_err = tool_json(client.call_tool(
                    "istsos_list_datastreams", {"thing_id": 1}))
                ok = (not is_err) and data and data.get("count") == 1 and \
                    data["datastreams"][0]["id"] == 1
                report("5-list-datastreams", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("5-list-datastreams", False, str(e))

            # 6) get_observations limit=2
            try:
                data, is_err = tool_json(client.call_tool(
                    "istsos_get_observations",
                    {"datastream_id": 1, "limit": 2}))
                ok = (not is_err) and data and data.get("count") == 2
                report("6-get-observations", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("6-get-observations", False, str(e))

            # 7) limit 超限必须被拒
            try:
                data, is_err = tool_json(client.call_tool(
                    "istsos_get_observations",
                    {"datastream_id": 1, "limit": 101}))
                ok = data and data.get("error_code") == "LIMIT_EXCEEDED"
                report("7-limit-exceeded", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("7-limit-exceeded", False, str(e))

            # 8) 无 token 必须被拒
            try:
                text, is_err = tool_text(client.call_tool(
                    "istsos_ping", token=None))
                ok = bool(is_err) and "BAD_TOKEN" in text
                report("8-no-token", ok, text.strip()[:120])
            except Exception as e:
                report("8-no-token", False, str(e))

            # 9) 错 token 必须被拒
            try:
                text, is_err = tool_text(client.call_tool(
                    "istsos_ping", token="definitely-wrong-token"))
                ok = bool(is_err) and "BAD_TOKEN" in text
                report("9-bad-token", ok, text.strip()[:120])
            except Exception as e:
                report("9-bad-token", False, str(e))

            # 10) export 落盘与内容
            try:
                data, is_err = tool_json(client.call_tool(
                    "istsos_export_observations_geojson",
                    {"datastream_id": 1, "limit": 10}))
                ok = (not is_err) and data and data.get("ok") and \
                    data.get("features") == 3
                detail = json.dumps(data)[:140]
                if ok:
                    with open(data["path"], "r", encoding="utf-8") as f:
                        gj = json.load(f)
                    feats = gj.get("features") or []
                    ok = gj.get("type") == "FeatureCollection" and \
                        len(feats) == 3 and \
                        feats[0]["geometry"] == FAKE_LOCATION and \
                        feats[0]["properties"]["result"] == 23.1
                    detail += " | geojson features=%d geom=%s" % (
                        len(feats),
                        feats[0]["geometry"] if feats else None)
                report("10-export-geojson", bool(ok), detail)
            except Exception as e:
                report("10-export-geojson", False, str(e))
    finally:
        stop_mcp(proc)

    # 11) 只读纪律：假服务端只应收到 GET
    methods = {m for m, _p in REQUESTS}
    report("11-get-only", methods == {"GET"},
           "假服务端收到的方法集合: %s（共 %d 次请求）"
           % (sorted(methods), len(REQUESTS)))

    # 12) 未配置基地址时必须诚实报 NOT_CONFIGURED
    proc2 = start_mcp({"ISTSOS_BRIDGE_TOKEN": TEST_TOKEN})
    try:
        client2, _info = init_client(proc2)
        data, is_err = tool_json(client2.call_tool("istsos_list_things"))
        ok = data and data.get("error_code") == "NOT_CONFIGURED"
        report("12-not-configured", bool(ok), json.dumps(data)[:140])
    except Exception as e:
        report("12-not-configured", False, str(e))
    finally:
        stop_mcp(proc2)

    server.shutdown()
    passed = sum(1 for _n, ok in RESULTS if ok)
    print("SELFTEST: %d/%d PASS" % (passed, len(RESULTS)))
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
