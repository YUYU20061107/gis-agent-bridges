# -*- coding: utf-8 -*-
"""
probe_api.py — GNSS×GIS 验证桥离线探针（纯标准库，只读）

在把轨迹交给 MCP 服务端之前，先用这个脚本独立探一次运行环境，
结果留档。探针与 live/mcp_server.py 同口径：只读 GNSS_WORK_DIR
内的文件；内置检查用包自带 examples/ 的合成轨迹与参考道路
（期望值独立手算，见 live/selftest.py 的口径说明），验证解析、
偏离与跳点三条主链路；不写任何文件、不联网。

依次探：Python 版本 → GNSS_WORK_DIR 是否配置/存在 → 合成轨迹
解析（点数、fix 分布）→ 对参考道路的偏离（已知偏离点是否被
数出来）→ 跳点检测（已知跳点是否被抓到）。任何一步失败都如实
记进对应字段，不中断后续探针。

用法：python3 scripts/probe_api.py
退出码：0 = 环境与内置样本链路都正常（ready=true）；1 = 有问题。
注意：探通只证明离线链路能跑；真实轨迹的对账（手机实走＋真实
参考层）须按 docs/CALIBRATION.md 用桥之外的独立来源完成。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gnss_bridge as nb  # noqa: E402

PROBE_NAME = "gnss-validation-bridge"
PROBE_VERSION = "0.1.0"
PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(PKG_DIR, "examples")


def _try(fn):
    try:
        return {"ok": True, "value": fn()}
    except nb.BridgeError as e:
        return {"ok": False, "error_code": e.error_code,
                "message": e.message}
    except Exception as e:
        return {"ok": False, "error_code": "PROBE_ERROR",
                "message": "%r" % (e,)}


def main():
    result = {"probe": PROBE_NAME, "version": PROBE_VERSION,
              "python": sys.version.split()[0],
              "work_dir_env": nb.work_dir(),
              "max_track_points": nb.MAX_TRACK_POINTS}
    wd = nb.work_dir()
    result["work_dir_exists"] = bool(wd) and os.path.isdir(wd)
    # 内置样本链路：临时把工作目录指向 examples/（只读使用）
    old = os.environ.get("GNSS_WORK_DIR")
    os.environ["GNSS_WORK_DIR"] = EXAMPLES
    try:
        track = _try(lambda: nb.load_track("sample-track.nmea"))
        if track["ok"]:
            points, meta = track["value"]
            result["sample_track"] = {
                "ok": True, "format": meta["format"],
                "summary": nb.summarize_points(points),
                "parse_info": meta["parse_info"]}
            layer = _try(lambda: nb.load_layer("sample-road.geojson"))
            if layer["ok"]:
                devs = []
                for p in points:
                    d, _q = nb.distance_to_layer(p["lat"], p["lon"],
                                                 layer["value"])
                    devs.append(d)
                over = [round(d, 2) for d in devs if d > 10.0]
                result["sample_validate"] = {
                    "ok": True, "deviation": nb.dist_stats(devs),
                    "over_10m_distances": over}
                finds, _notes = nb.detect_anomalies(points)
                result["sample_jumps"] = {
                    "ok": True,
                    "speed_flagged_seqs": sorted(
                        {f["seq"] for f in finds
                         if f["kind"] == "speed"})}
            else:
                result["sample_validate"] = layer
        else:
            result["sample_track"] = track
    finally:
        if old is None:
            os.environ.pop("GNSS_WORK_DIR", None)
        else:
            os.environ["GNSS_WORK_DIR"] = old
    checks_ok = (
        result["work_dir_exists"] and
        (result.get("sample_track") or {}).get("ok") and
        (result.get("sample_validate") or {}).get("ok") and
        (result.get("sample_jumps") or {}).get("ok"))
    result["ok"] = bool(checks_ok)
    result["ready"] = bool(checks_ok)
    if not result["work_dir_exists"]:
        result["message"] = ("GNSS_WORK_DIR 未配置或目录不存在：服务端"
                             "文件类工具会以 NOT_CONFIGURED 拒绝；先建"
                             "工作目录并把轨迹/图层放进去")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if checks_ok else 1


if __name__ == "__main__":
    sys.exit(main())
