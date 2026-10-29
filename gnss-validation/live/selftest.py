# -*- coding: utf-8 -*-
"""
selftest.py — GNSS×GIS 验证桥一键自检（纯标准库，无需 GNSS 设备）

自检数据全部为合成数据，期望值独立手算，不取桥自身产出当期望：
  * examples/sample-track.nmea —— 10 个点（1 s/点、沿东向约 10 m/s），
    其中 seq 3 已知北偏 0.00018°（111194.93 m/° × 0.00018 ≈ 20.015 m，
    参考道路是纬度 22.0 的直线，偏离即该值）；seq 7 已知沿轨多跳
    +0.001° 经度（该纬度 1° 经度 ≈ 103089 m，故段速 seq6→7 ≈
    113.1 m/s、seq7→8 ≈ 93.1 m/s，均应被 60 m/s 阈值抓住；其余段
    速 ≈10 或 22.4 m/s 不应误报）；另含 1 条无定位 GGA 与 1 条
    校验和篡改语句，应分别计入 no_fix_lines / bad_checksum。
  * examples/sample-road.geojson —— 纬度 22.0 的直线道路。
  * 自检临时生成的 drift.nmea —— 40 个静止抖动点（对质心 ±2.7 m
    交替、净位移 <5 m、持续 39 s）：应被静止漂移检出（RMS≈2.65>2）。
  * 自检临时生成的 big.nmea —— 10050 个点：验证 10000 硬上限截断。
  * 自检临时生成的 track.gpx —— 3 个 GPX 点：验证 GPX 解析路径。

检查（22 项）：
  1) initialize         —— MCP 握手与 serverInfo
  2) tools/list         —— 8 个 gnss_* 工具齐全不多不少
  3) status 正例        —— 点数/fix 分布/HDOP/时间跨度/解析计数与手算一致
  4) track_read 正例    —— 10 点全回、seq3 坐标正确
  5) track_read 截断    —— limit=4 只回 4 点且 truncated=true
  6) track_read GPX     —— GPX 路径解析出 3 点
  7) 无 token           —— BAD_TOKEN
  8) 错误 token         —— BAD_TOKEN
  9) 路径穿越           —— ../outside.nmea 被 PATH_OUTSIDE_WORKDIR 拒绝
  10) 绝对路径          —— 绝对路径同样被拒绝
  11) validate 正例     —— 超限清单恰为 seq3、距离 ≈20.015 m
  12) detect_jumps 正例 —— seq7/8 被段速抓住、seq1–6 不误报；漂移文件被检出
  13) accuracy 有图层   —— GPS 组 count=8、RMS ≈7.076 m（手算）
  14) accuracy 无图层   —— basis=self-consistency 且明示不是精度真值
  15) snap 未 confirm   —— CONFIRM_REQUIRED 且不落盘
  16) snap 正例         —— 文件落盘、seq3 修正量 ≈20.015 m
  17) snap 重名输出     —— OUTPUT_EXISTS 拒绝覆盖
  18) smooth 正例       —— window=3 时 seq3 修正量 ≈13.34 m；偶数窗口被拒
  19) offset 双配对     —— 纠偏后首点坐标与真值一致（偏移手算）
  20) offset 单配对     —— 只报偏移、corrected=false、不产文件
  21) offset 未 confirm —— CONFIRM_REQUIRED 且不落盘
  22) 硬上限            —— 10050 点文件以 limit=20000 读只回 10000 且截断明示
逐项打印 PASS/FAIL，最后一行总结果；退出码 0=全过，1=有失败。
口径声明：本自检只证明协议、解析与安全闸成立（协议自检级），不证明
已用真实 GNSS 轨迹与真实参考图层对账；实机校准见 docs/CALIBRATION.md。
自检把 HOME 与 GNSS_WORK_DIR 都指到临时目录，产物不落包目录。
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
EXAMPLES = os.path.join(PKG, "examples")
MCP_PY = os.path.join(HERE, "mcp_server.py")
TEST_TOKEN = "gnss-selftest-token"

EXPECTED_TOOLS = {
    "gnss_status", "gnss_track_read", "gnss_validate_against_layer",
    "gnss_detect_jumps", "gnss_accuracy_report", "gnss_correct_snap",
    "gnss_correct_smooth", "gnss_correct_offset",
}

RESULTS = []


def report(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" — " + detail) if detail else ""), flush=True)


def _cs(body):
    c = 0
    for ch in body:
        c ^= ord(ch)
    return "%02X" % c


def _latlon_s(lat, lon):
    la = "%02d%08.5f" % (int(abs(lat)), (abs(lat) - int(abs(lat))) * 60.0)
    lo = "%03d%08.5f" % (int(abs(lon)), (abs(lon) - int(abs(lon))) * 60.0)
    return la, lo


def _gga(sec, lat, lon, fix=1, sats=10, hdop=1.0):
    t = "03%02d%02d.00" % (sec // 60, sec % 60)
    la, lo = _latlon_s(lat, lon)
    body = "GPGGA,%s,%s,N,%s,E,%d,%02d,%.1f,10.0,M,0.0,M,," % (
        t, la, lo, fix, sats, hdop)
    return "$%s*%s" % (body, _cs(body))


def _rmc(sec, lat, lon):
    # GGA-only 文件没有日期、点上不了时间轴；漂移/速度类样本须配 RMC
    t = "03%02d%02d.00" % (sec // 60, sec % 60)
    la, lo = _latlon_s(lat, lon)
    body = "GPRMC,%s,A,%s,N,%s,E,0.00,0.0,291026,,,A" % (t, la, lo)
    return "$%s*%s" % (body, _cs(body))


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

    def readline(self, timeout=20):
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
        return json.loads(self._reader.readline(20))

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
    tmp = tempfile.mkdtemp(prefix="gnss-selftest-")
    work = os.path.join(tmp, "work")
    home_dir = os.path.join(tmp, "home")
    os.makedirs(work)
    os.makedirs(home_dir)
    for name in ("sample-track.nmea", "sample-road.geojson"):
        shutil.copy(os.path.join(EXAMPLES, name), os.path.join(work, name))
    # 静止漂移样本：质心 (22.0, 113.0)，纬度交替 ±2.7 m（≈2.428e-5°）
    drift_lines = []
    offs = [0.0, 2.428e-5, -2.428e-5]
    for i in range(40):
        drift_lines.append(_gga(i, 22.0 + offs[i % 3], 113.0))
        drift_lines.append(_rmc(i, 22.0 + offs[i % 3], 113.0))
    with open(os.path.join(work, "drift.nmea"), "w", encoding="utf-8") as f:
        f.write("\n".join(drift_lines) + "\n")
    # 硬上限样本：10050 点
    with open(os.path.join(work, "big.nmea"), "w", encoding="utf-8") as f:
        for i in range(10050):
            f.write(_gga(i % 3600, 22.0, 113.0 + i * 1e-7) + "\n")
    # GPX 样本：3 点（2026-10-29T02:00:00Z 起 10 s 间隔）
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.1" creator="selftest" '
           'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
           '<trkpt lat="22.0000000" lon="113.0000000">'
           '<time>2026-10-29T02:00:00Z</time><fix>3d</fix><sat>10</sat>'
           '<hdop>0.9</hdop></trkpt>'
           '<trkpt lat="22.0000000" lon="113.0001000">'
           '<time>2026-10-29T02:00:10Z</time><fix>3d</fix><sat>10</sat>'
           '<hdop>1.0</hdop></trkpt>'
           '<trkpt lat="22.0000500" lon="113.0002000">'
           '<time>2026-10-29T02:00:20Z</time><fix>3d</fix><sat>9</sat>'
           '<hdop>1.1</hdop></trkpt>'
           '</trkseg></trk></gpx>\n')
    with open(os.path.join(work, "track.gpx"), "w", encoding="utf-8") as f:
        f.write(gpx)

    env = dict(os.environ)
    env.update({"HOME": home_dir, "GNSS_BRIDGE_TOKEN": TEST_TOKEN,
                "GNSS_WORK_DIR": work})
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
            ok = info.get("name") == "gnss-validation-bridge" and \
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

        # 3) status 正例
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_status", {"path": "sample-track.nmea"}))
            fc = (data or {}).get("fix_counts") or {}
            hd = (data or {}).get("hdop") or {}
            pi = (data or {}).get("parse_info") or {}
            ok = (not is_err) and data and data.get("points") == 10 and \
                fc.get("GPS") == 8 and fc.get("DGPS") == 1 and \
                fc.get("RTK固定") == 1 and hd.get("min") == 0.7 and \
                hd.get("max") == 2.6 and data.get("time_span_s") == 9.0 and \
                pi.get("bad_checksum") == 1 and pi.get("no_fix_lines") == 1
            report("3-status-ok", ok, json.dumps(data, ensure_ascii=False)[:200])
        except Exception as e:
            report("3-status-ok", False, str(e))

        # 4) track_read 正例
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_track_read", {"path": "sample-track.nmea"}))
            pts = (data or {}).get("points") or []
            ok = (not is_err) and data and \
                data.get("returned_points") == 10 and \
                data.get("truncated") is False and len(pts) == 10 and \
                abs(pts[3]["lat"] - 22.00018) < 1e-6
            report("4-track-read-ok", ok,
                   json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("4-track-read-ok", False, str(e))

        # 5) track_read 截断
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_track_read",
                {"path": "sample-track.nmea", "limit": 4}))
            ok = (not is_err) and data and \
                data.get("returned_points") == 4 and \
                data.get("total_points") == 10 and \
                data.get("truncated") is True
            report("5-track-read-truncate", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("5-track-read-truncate", False, str(e))

        # 6) GPX 解析
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_track_read", {"path": "track.gpx"}))
            ok = (not is_err) and data and data.get("format") == "GPX" and \
                data.get("returned_points") == 3
            report("6-gpx-read", ok, json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("6-gpx-read", False, str(e))

        # 7) 无 token
        try:
            text, is_err = tool_text(client.call_tool(
                "gnss_status", {"path": "sample-track.nmea"}, token=None))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("7-no-token", ok, text.strip()[:120])
        except Exception as e:
            report("7-no-token", False, str(e))

        # 8) 错误 token
        try:
            text, is_err = tool_text(client.call_tool(
                "gnss_status", {"path": "sample-track.nmea"},
                token="definitely-wrong-token"))
            ok = bool(is_err) and "BAD_TOKEN" in text
            report("8-bad-token", ok, text.strip()[:120])
        except Exception as e:
            report("8-bad-token", False, str(e))

        # 9) 路径穿越
        try:
            data, _e = tool_json(client.call_tool(
                "gnss_status", {"path": "../outside.nmea"}))
            ok = data and data.get("error_code") == "PATH_OUTSIDE_WORKDIR"
            report("9-path-traversal", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("9-path-traversal", False, str(e))

        # 10) 绝对路径
        try:
            data, _e = tool_json(client.call_tool(
                "gnss_status",
                {"path": os.path.join(work, "sample-track.nmea")}))
            ok = data and data.get("error_code") == "PATH_OUTSIDE_WORKDIR"
            report("10-absolute-path", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("10-absolute-path", False, str(e))

        # 11) validate 正例
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_validate_against_layer",
                {"path": "sample-track.nmea", "layer": "sample-road.geojson",
                 "threshold_m": 10}))
            over = (data or {}).get("over_threshold") or []
            dev = (data or {}).get("deviation") or {}
            ok = (not is_err) and data and \
                data.get("over_threshold_count") == 1 and \
                len(over) == 1 and over[0]["seq"] == 3 and \
                abs(over[0]["distance_m"] - 20.015) < 0.6 and \
                dev.get("count") == 10 and dev.get("median_m") == 0.0
            report("11-validate-ok", ok,
                   json.dumps(data, ensure_ascii=False)[:200])
        except Exception as e:
            report("11-validate-ok", False, str(e))

        # 12) detect_jumps 正例（样本跳点 + 漂移文件）
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_detect_jumps", {"path": "sample-track.nmea"}))
            susp = (data or {}).get("suspicious") or []
            speed_seqs = {f["seq"] for f in susp if f["kind"] == "speed"}
            data2, is_err2 = tool_json(client.call_tool(
                "gnss_detect_jumps", {"path": "drift.nmea"}))
            drift_hit = any(f["kind"] == "drift"
                            for f in ((data2 or {}).get("suspicious") or []))
            ok = (not is_err) and (not is_err2) and \
                {7, 8} <= speed_seqs and \
                not (speed_seqs & {1, 2, 3, 4, 5, 6}) and drift_hit
            report("12-detect-ok", ok,
                   "speed_seqs=%s drift=%s" % (sorted(speed_seqs), drift_hit))
        except Exception as e:
            report("12-detect-ok", False, str(e))

        # 13) accuracy 有图层
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_accuracy_report",
                {"path": "sample-track.nmea", "layer": "sample-road.geojson"}))
            gps = ((data or {}).get("by_fix") or {}).get("GPS") or {}
            ok = (not is_err) and data and \
                data.get("basis") == "reference-layer-deviation" and \
                (data.get("overall") or {}).get("count") == 10 and \
                gps.get("count") == 8 and \
                gps.get("rms_m") is not None and \
                abs(gps["rms_m"] - 7.076) < 0.3
            report("13-accuracy-layer", ok,
                   json.dumps(data, ensure_ascii=False)[:200])
        except Exception as e:
            report("13-accuracy-layer", False, str(e))

        # 14) accuracy 无图层退化口径
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_accuracy_report", {"path": "sample-track.nmea"}))
            ok = (not is_err) and data and \
                data.get("basis") == "self-consistency" and \
                "不是精度真值" in (data.get("note") or "")
            report("14-accuracy-nolayer", ok,
                   json.dumps(data, ensure_ascii=False)[:160])
        except Exception as e:
            report("14-accuracy-nolayer", False, str(e))

        # 15) snap 未 confirm
        snap_out = os.path.join(work, "snapped.geojson")
        try:
            data, _e = tool_json(client.call_tool(
                "gnss_correct_snap",
                {"path": "sample-track.nmea", "layer": "sample-road.geojson",
                 "output": "snapped.geojson"}))
            ok = data and data.get("error_code") == "CONFIRM_REQUIRED" and \
                not os.path.exists(snap_out)
            report("15-snap-no-confirm", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("15-snap-no-confirm", False, str(e))

        # 16) snap 正例
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_correct_snap",
                {"path": "sample-track.nmea", "layer": "sample-road.geojson",
                 "output": "snapped.geojson", "confirm": True}))
            corr3 = None
            file_ok = False
            if os.path.isfile(snap_out):
                with open(snap_out, "r", encoding="utf-8") as fh:
                    gj = json.load(fh)
                feats = gj.get("features") or []
                file_ok = len(feats) == 10
                for ft in feats:
                    if (ft.get("properties") or {}).get("seq") == 3:
                        corr3 = ft["properties"]["correction_m"]
            ok = (not is_err) and data and data.get("written") is True and \
                file_ok and corr3 is not None and abs(corr3 - 20.015) < 0.6
            report("16-snap-ok", ok, json.dumps(data, ensure_ascii=False)[:180])
        except Exception as e:
            report("16-snap-ok", False, str(e))

        # 17) snap 重名输出拒绝覆盖
        try:
            data, _e = tool_json(client.call_tool(
                "gnss_correct_snap",
                {"path": "sample-track.nmea", "layer": "sample-road.geojson",
                 "output": "snapped.geojson", "confirm": True}))
            ok = data and data.get("error_code") == "OUTPUT_EXISTS"
            report("17-snap-exists", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("17-snap-exists", False, str(e))

        # 18) smooth 正例 + 偶数窗口被拒
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_correct_smooth",
                {"path": "sample-track.nmea", "window": 3,
                 "output": "smoothed.geojson", "confirm": True}))
            spath = os.path.join(work, "smoothed.geojson")
            corr3 = None
            if os.path.isfile(spath):
                with open(spath, "r", encoding="utf-8") as fh:
                    gj = json.load(fh)
                for ft in gj.get("features") or []:
                    if (ft.get("properties") or {}).get("seq") == 3:
                        corr3 = ft["properties"]["correction_m"]
            data2, _e2 = tool_json(client.call_tool(
                "gnss_correct_smooth",
                {"path": "sample-track.nmea", "window": 4,
                 "output": "smoothed2.geojson", "confirm": True}))
            ok = (not is_err) and data and data.get("written") is True and \
                corr3 is not None and 12.0 < corr3 < 15.0 and \
                data2 and data2.get("error_code") == "BAD_ARGUMENT"
            report("18-smooth-ok", ok,
                   "corr3=%s even=%s" % (corr3,
                       (data2 or {}).get("error_code")))
        except Exception as e:
            report("18-smooth-ok", False, str(e))

        # 19) offset 双配对
        pairs2 = [
            {"observed_lat": 22.0000000, "observed_lon": 113.0000000,
             "truth_lat": 22.0000200, "truth_lon": 113.0000100},
            {"observed_lat": 22.0000000, "observed_lon": 113.0004850,
             "truth_lat": 22.0000200, "truth_lon": 113.0004950},
        ]
        off_out = os.path.join(work, "offset.geojson")
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_correct_offset",
                {"path": "sample-track.nmea", "pairs": pairs2,
                 "output": "offset.geojson", "confirm": True}))
            first = None
            if os.path.isfile(off_out):
                with open(off_out, "r", encoding="utf-8") as fh:
                    gj = json.load(fh)
                first = (gj.get("features") or [{}])[0] \
                    .get("geometry", {}).get("coordinates")
            mo = (data or {}).get("mean_offset") or {}
            ok = (not is_err) and data and \
                data.get("corrected") is True and \
                first is not None and \
                abs(first[0] - 113.0000100) < 2e-6 and \
                abs(first[1] - 22.0000200) < 2e-6 and \
                mo.get("magnitude_m") is not None and \
                abs(mo["magnitude_m"] - 2.452) < 0.05
            report("19-offset-two", ok,
                   json.dumps(data, ensure_ascii=False)[:200])
        except Exception as e:
            report("19-offset-two", False, str(e))

        # 20) offset 单配对只报不纠
        single_out = os.path.join(work, "offset-single.geojson")
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_correct_offset",
                {"path": "sample-track.nmea", "pairs": pairs2[:1],
                 "output": "offset-single.geojson", "confirm": True}))
            ok = (not is_err) and data and \
                data.get("corrected") is False and \
                data.get("written") is False and \
                not os.path.exists(single_out)
            report("20-offset-single", ok,
                   json.dumps(data, ensure_ascii=False)[:180])
        except Exception as e:
            report("20-offset-single", False, str(e))

        # 21) offset 未 confirm
        nc_out = os.path.join(work, "offset-nc.geojson")
        try:
            data, _e = tool_json(client.call_tool(
                "gnss_correct_offset",
                {"path": "sample-track.nmea", "pairs": pairs2,
                 "output": "offset-nc.geojson"}))
            ok = data and data.get("error_code") == "CONFIRM_REQUIRED" and \
                not os.path.exists(nc_out)
            report("21-offset-no-confirm", ok,
                   json.dumps(data, ensure_ascii=False)[:140])
        except Exception as e:
            report("21-offset-no-confirm", False, str(e))

        # 22) 硬上限截断
        try:
            data, is_err = tool_json(client.call_tool(
                "gnss_track_read", {"path": "big.nmea", "limit": 20000}))
            ok = (not is_err) and data and \
                data.get("total_points") == 10050 and \
                data.get("returned_points") == 10000 and \
                data.get("truncated") is True
            report("22-hard-cap", ok, json.dumps(
                {k: (data or {}).get(k) for k in
                 ("total_points", "returned_points", "truncated")},
                ensure_ascii=False))
        except Exception as e:
            report("22-hard-cap", False, str(e))
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
