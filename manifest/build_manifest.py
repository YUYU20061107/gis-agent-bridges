# -*- coding: utf-8 -*-
"""
build_manifest.py — 由代码生成机读工具清单 manifest/tools-manifest.json

做法：逐包实际启动 live/mcp_server.py（纯标准库 stdio MCP，无厂商依赖），
发送 initialize + tools/list，取回 serverInfo 与工具定义。取不到的包
在清单里如实标注 error 与原因，本脚本以 exit 1 结束（供 CI 拦截）。

读写分类口径（与各包工具描述的既有标注一致）：
  - 描述以「【视图级」开头            -> access = "view"（只改显示状态、可逆）
  - 描述含「【写」或「【执行」，或
    inputSchema 带 confirm 属性       -> access = "write"
  - 工具名为 *_export_*（导出到调用方
    指定路径的新文件，按现行设计无
    confirm 闸）                       -> access = "write"，note 标注 file-output
  - 其余                              -> access = "read"
  requires_confirm 以 inputSchema 是否含 confirm 属性为准（事实字段，
  与 access 分类相互独立）。

注意：本脚本验证的是「离线协议层」（offline protocol self-check）：
服务端能启动、能列工具，不代表已在真实 GIS 软件上完成实机校准。
校准状态以根 README 与各包 docs/CALIBRATION.md 为准。

用法：python3 manifest/build_manifest.py [--root <仓库根>]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

PACKAGES = ["supermap", "arcgis-pro", "arcmap", "qgis", "geoscene",
            "mapgis", "envi", "globalmapper", "fme"]

# 端口以根 README「端口分配」为准；无常驻应用内桥的包为 None。
PORTS = {"supermap": 47615, "arcgis-pro": 47616, "arcmap": 47617,
         "qgis": 47618, "geoscene": 47619, "mapgis": None, "envi": None,
         "globalmapper": None, "fme": None}


def classify(name, desc, props):
    keys = list((props or {}).keys())
    requires_confirm = "confirm" in keys
    note = None
    if desc.startswith("【视图级"):
        access = "view"
    elif requires_confirm or ("【写" in desc) or ("【执行" in desc):
        access = "write"
    elif "_export_" in name:
        access = "write"
        note = "file-output: creates a new file at a caller-specified path; no confirm gate by design"
    else:
        access = "read"
    return access, requires_confirm, note


def probe(root, pkg, timeout=30):
    srv = os.path.join(root, pkg, "live", "mcp_server.py")
    if not os.path.isfile(srv):
        return {"package": pkg, "error": "MCP_SERVER_MISSING",
                "reason": "live/mcp_server.py 不存在"}
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    tmp_home = tempfile.mkdtemp(prefix="manifest-home-")
    env["HOME"] = tmp_home
    req = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {}}) + "\n" +
           json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                       "params": {}}) + "\n")
    try:
        pr = subprocess.Popen([sys.executable, srv], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env)
        out, _err = pr.communicate(req.encode("utf-8"), timeout=timeout)
    except Exception as e:
        return {"package": pkg, "error": "PROBE_FAILED", "reason": "%r" % (e,)}
    info = None
    tools = None
    for line in out.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("id") == 1:
            info = (msg.get("result") or {}).get("serverInfo")
        elif msg.get("id") == 2:
            tools = (msg.get("result") or {}).get("tools")
    if info is None or tools is None:
        return {"package": pkg, "error": "PROBE_FAILED",
                "reason": "服务端未返回 initialize/tools-list 结果"}
    entries = []
    for t in tools:
        schema = t.get("inputSchema") or {}
        access, req_conf, note = classify(t.get("name", ""),
                                          t.get("description") or "",
                                          schema.get("properties"))
        item = {"name": t.get("name"), "access": access,
                "requires_confirm": req_conf,
                "description": t.get("description") or ""}
        if note:
            item["note"] = note
        entries.append(item)
    return {"package": pkg,
            "server_name": info.get("name"),
            "server_version": info.get("version"),
            "port": PORTS.get(pkg),
            "tool_count": len(entries),
            "tools": entries}


def main():
    ap = argparse.ArgumentParser(prog="build_manifest")
    ap.add_argument("--root", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    out_path = args.out or os.path.join(root, "manifest", "tools-manifest.json")
    packages = [probe(root, p) for p in PACKAGES]
    manifest = {
        "generated_by": "manifest/build_manifest.py",
        "method": "live probe: launch each live/mcp_server.py, MCP initialize + tools/list",
        "scope_note": ("Offline protocol self-check only: proves each stdio MCP "
                       "server starts and lists its tools. It is NOT evidence "
                       "of calibration against real GIS software; see root "
                       "README and each package docs/CALIBRATION.md."),
        "packages": packages,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    failed = [p for p in packages if "error" in p]
    for p in packages:
        if "error" in p:
            print("%-13s ERROR %s: %s" % (p["package"], p["error"], p["reason"]))
        else:
            print("%-13s %s v%s port=%s tools=%d" % (
                p["package"], p["server_name"], p["server_version"],
                p["port"], p["tool_count"]))
    print("wrote %s" % out_path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
