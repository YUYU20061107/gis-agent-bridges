# -*- coding: utf-8 -*-
"""
selftest.py — STAC 消费侧只读桥一键自检（纯标准库，无需任何真实服务）

自检在本机 127.0.0.1 随机端口起一个“假 STAC 服务端”（只回放固定
JSON），再启动 live/mcp_server.py 子进程对着它跑，自动检查：
  1)  initialize        —— MCP 握手与 serverInfo（stac-consumer-bridge 0.1.x）
  2)  tools/list        —— 6 个 stac_* 只读工具齐全、无多余
  3)  ping              —— 经假服务端落地页确认 server_reachable=true
  4)  list_collections  —— 回放的 2 个集合数量与 id 对得上
  5)  get_collection    —— 许可与空间范围与回放一致
  6)  search_items      —— limit=2 时只回 2 条，云量字段对得上
  7)  limit 超限        —— limit=101 必须以 LIMIT_EXCEEDED 被拒（不许静默截断）
  8)  bbox 非法         —— min>max 的 bbox 必须以 BAD_BBOX 在发请求前被拒
  9)  无 token          —— 不带 _token 的调用必须被 BAD_TOKEN 拒绝
  10) 错 token          —— 错误 _token 必须被 BAD_TOKEN 拒绝
  11) export            —— 导出 GeoJSON 真实落盘：FeatureCollection、
                           3 个 Feature、足印几何与首条云量对得上
  12) 只读纪律          —— 假服务端收到的请求必须全部是 GET
  13) 未配置诚实性      —— 另起一个不带 STAC_BASE_URL 的服务端进程，
                           list_collections 必须报 NOT_CONFIGURED
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。

注意口径：本自检只证明“桥对着一个回放固定 JSON 的假 STAC 服务端
时，协议与参数校验行为正确”，属于协议级自检。真实 STAC 目录未
实测，自检通过不等于任何真实目录已验证，见 docs/CALIBRATION.md。
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
TEST_TOKEN = "stac-selftest-token"

EXPECTED_TOOLS = {
    "stac_ping", "stac_discover", "stac_list_collections",
    "stac_get_collection", "stac_search_items",
    "stac_export_items_geojson",
}

RESULTS = []
REQUESTS = []  # 假服务端收到的 (method, path)

FAKE_GEOMETRY = {"type": "Polygon", "coordinates": [[
    [112.0, 20.0], [113.0, 20.0], [113.0, 21.0], [112.0, 21.0],
    [112.0, 20.0]]]}
FAKE_ITEMS = [
    {"type": "Feature", "id": "S2A_001", "collection": "sentinel-2-l2a",
     "geometry": FAKE_GEOMETRY,
     "properties": {"datetime": "2026-01-03T03:00:00Z",
                    "eo:cloud_cover": 12.5, "platform": "sentinel-2a",
                    "instruments": ["msi"]},
     "assets": {"visual": {"href": "http://x/visual.tif"},
                "thumbnail": {"href": "http://x/thumb.jpg"}}},
    {"type": "Feature", "id": "S2A_002", "collection": "sentinel-2-l2a",
     "geometry": FAKE_GEOMETRY,
     "properties": {"datetime": "2026-01-02T03:00:00Z",
                    "eo:cloud_cover": 40.0, "platform": "sentinel-2a",
                    "instruments": ["msi"]},
     "assets": {"visual": {"href": "http://x/visual2.tif"}}},
    {"type": "Feature", "id": "S2A_003", "collection": "sentinel-2-l2a",
     "geometry": FAKE_GEOMETRY,
     "properties": {"datetime": "2026-01-01T03:00:00Z",
                    "eo:cloud_cover": 3.25, "platform": "sentinel-2b",
                    "instruments": ["msi"]},
     "assets": {"visual": {"href": "http://x/visual3.tif"}}},
]
FAKE_COLLECTION = {
    "type": "Collection", "id": "sentinel-2-l2a",
    "title": "Sentinel-2 L2A", "description": "fake sentinel-2 collection",
    "license": "CC-BY-4.0", "stac_version": "1.0.0",
    "keywords": ["sentinel", "fake"],
    "extent": {"spatial": {"bbox": [[112.0, 20.0, 113.0, 21.0]]},
               "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}},
    "providers": [{"name": "Fake Provider", "roles": ["producer"]}],
}


def fake_response(path, query):
    """按 STAC API 的基本形状回放固定 JSON；/search 认 limit。"""
    if path in ("/stac", "/stac/"):
        return {"type": "Catalog", "id": "fake-stac",
                "title": "Fake STAC Catalog",
                "conformsTo": ["https://api.stacspec.org/v1.0.0/core",
                               "https://api.stacspec.org/v1.0.0/item-search"],
                "links": [{"rel": "self", "href": "http://x/stac"},
                          {"rel": "data", "href": "http://x/stac/collections"},
                          {"rel": "search", "href": "http://x/stac/search"}]}
    if path == "/stac/collections":
        other = dict(FAKE_COLLECTION)
        other["id"] = "landsat-c2-l2"
        other["title"] = "Landsat C2 L2"
        return {"collections": [FAKE_COLLECTION, other], "links": []}
    if path == "/stac/collections/sentinel-2-l2a":
        return FAKE_COLLECTION
    if path == "/stac/search":
        limit = None
        if "limit" in query:
            try:
                limit = int(query["limit"][0])
            except Exception:
                limit = None
        items = FAKE_ITEMS[:limit] if limit is not None else FAKE_ITEMS
        return {"type": "FeatureCollection", "features": items,
                "numberMatched": len(FAKE_ITEMS),
                "numberReturned": len(items)}
    return None


class FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _record_and_reply(self, method):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        REQUESTS.append((method, parsed.path))
        if method != "GET":
            body = json.dumps({"error": "GET only"}).encode()
            self.send_response(405)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data = fake_response(parsed.path, query)
        if data is None:
            body = json.dumps({"error": "not found"}).encode()
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
    """逐行读取子进程 stdout（后台线程 + 队列，与仓内自检同口径）。"""

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
    env.pop("STAC_BASE_URL", None)
    env.update(env_extra)
    env["HOME"] = tempfile.mkdtemp(prefix="stac-selftest-home-")
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
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/stac" % port
    out_dir = tempfile.mkdtemp(prefix="stac-selftest-out-")

    proc = start_mcp({"STAC_BASE_URL": base,
                      "STAC_BRIDGE_TOKEN": TEST_TOKEN,
                      "STAC_BRIDGE_OUTPUT_DIR": out_dir})
    client = None
    try:
        # 1) initialize
        try:
            client, info = init_client(proc)
            ok = info.get("name") == "stac-consumer-bridge" and \
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
                data, is_err = tool_json(client.call_tool("stac_ping"))
                ok = (not is_err) and data and data.get("pong") and \
                    data.get("server_reachable") is True and \
                    data.get("catalog_id") == "fake-stac"
                report("3-ping", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("3-ping", False, str(e))

            # 4) list_collections
            try:
                data, is_err = tool_json(client.call_tool(
                    "stac_list_collections"))
                ids = [c["id"] for c in data.get("collections", [])] \
                    if data else []
                ok = (not is_err) and data and data.get("count") == 2 and \
                    ids == ["sentinel-2-l2a", "landsat-c2-l2"]
                report("4-list-collections", bool(ok),
                       json.dumps(data)[:140])
            except Exception as e:
                report("4-list-collections", False, str(e))

            # 5) get_collection
            try:
                data, is_err = tool_json(client.call_tool(
                    "stac_get_collection",
                    {"collection_id": "sentinel-2-l2a"}))
                ok = (not is_err) and data and \
                    data.get("license") == "CC-BY-4.0" and \
                    data.get("spatial_bbox") == [112.0, 20.0, 113.0, 21.0]
                report("5-get-collection", bool(ok),
                       json.dumps(data)[:140])
            except Exception as e:
                report("5-get-collection", False, str(e))

            # 6) search limit=2
            try:
                data, is_err = tool_json(client.call_tool(
                    "stac_search_items",
                    {"collection_id": "sentinel-2-l2a", "limit": 2}))
                items = data.get("items") or [] if data else []
                ok = (not is_err) and data and data.get("count") == 2 and \
                    items[0]["id"] == "S2A_001" and \
                    items[0]["cloud_cover"] == 12.5 and \
                    items[0]["assets"] == ["thumbnail", "visual"]
                report("6-search-items", bool(ok), json.dumps(data)[:160])
            except Exception as e:
                report("6-search-items", False, str(e))

            # 7) limit 超限必须被拒
            try:
                data, _e = tool_json(client.call_tool(
                    "stac_search_items",
                    {"collection_id": "sentinel-2-l2a", "limit": 101}))
                ok = data and data.get("error_code") == "LIMIT_EXCEEDED"
                report("7-limit-exceeded", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("7-limit-exceeded", False, str(e))

            # 8) 非法 bbox 在发请求前被拒
            try:
                before = len(REQUESTS)
                data, _e = tool_json(client.call_tool(
                    "stac_search_items",
                    {"collection_id": "sentinel-2-l2a",
                     "bbox": [113.0, 20.0, 112.0, 21.0]}))
                ok = data and data.get("error_code") == "BAD_BBOX" and \
                    len(REQUESTS) == before
                report("8-bad-bbox", bool(ok), json.dumps(data)[:140])
            except Exception as e:
                report("8-bad-bbox", False, str(e))

            # 9) 无 token 必须被拒
            try:
                text, is_err = tool_text(client.call_tool(
                    "stac_ping", token=None))
                ok = bool(is_err) and "BAD_TOKEN" in text
                report("9-no-token", ok, text.strip()[:120])
            except Exception as e:
                report("9-no-token", False, str(e))

            # 10) 错 token 必须被拒
            try:
                text, is_err = tool_text(client.call_tool(
                    "stac_ping", token="definitely-wrong-token"))
                ok = bool(is_err) and "BAD_TOKEN" in text
                report("10-bad-token", ok, text.strip()[:120])
            except Exception as e:
                report("10-bad-token", False, str(e))

            # 11) export 落盘与内容
            try:
                data, is_err = tool_json(client.call_tool(
                    "stac_export_items_geojson",
                    {"collection_id": "sentinel-2-l2a", "limit": 10}))
                ok = (not is_err) and data and data.get("ok") and \
                    data.get("features") == 3
                detail = json.dumps(data)[:140]
                if ok:
                    with open(data["path"], "r", encoding="utf-8") as f:
                        gj = json.load(f)
                    feats = gj.get("features") or []
                    ok = gj.get("type") == "FeatureCollection" and \
                        len(feats) == 3 and \
                        feats[0]["geometry"] == FAKE_GEOMETRY and \
                        feats[0]["properties"]["cloud_cover"] == 12.5
                    detail += " | geojson features=%d" % len(feats)
                report("11-export-geojson", bool(ok), detail)
            except Exception as e:
                report("11-export-geojson", False, str(e))
    finally:
        stop_mcp(proc)

    # 12) 只读纪律：假服务端只应收到 GET
    methods = {m for m, _p in REQUESTS}
    report("12-get-only", methods == {"GET"},
           "假服务端收到的方法集合: %s（共 %d 次请求）"
           % (sorted(methods), len(REQUESTS)))

    # 13) 未配置基地址时必须诚实报 NOT_CONFIGURED
    proc2 = start_mcp({"STAC_BRIDGE_TOKEN": TEST_TOKEN})
    try:
        client2, _info = init_client(proc2)
        data, is_err = tool_json(client2.call_tool("stac_list_collections"))
        ok = data and data.get("error_code") == "NOT_CONFIGURED"
        report("13-not-configured", bool(ok), json.dumps(data)[:140])
    except Exception as e:
        report("13-not-configured", False, str(e))
    finally:
        stop_mcp(proc2)

    server.shutdown()
    passed = sum(1 for _n, ok in RESULTS if ok)
    print("SELFTEST: %d/%d PASS" % (passed, len(RESULTS)))
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
