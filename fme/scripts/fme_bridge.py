# -*- coding: utf-8 -*-
"""
fme_bridge.py — FME 无头 runner 桥接脚本（v0.1，本地无头）

子命令：
  preflight  环境预检：多策略探测 FME 安装与 fmeobjects 可导入性（只读）
  scan       扫描目录，列出 .fmw workspace 清单（只读）
  info       解析 .fmw 文本，尽力提取源/目标数据集与 transformer 信息（只读）
  backup     备份 .fmw 文件（时间戳副本 + sha256），纯标准库

定位与边界：
  - FME 没有"当前会话"接口，本脚本不接入任何 FME GUI 会话；info 是对 .fmw
    文本文件的尽力解析（best-effort），输出固定标注 mode=file-parse 与
    complete=false，宏 $(...) 不展开、INCLUDE 文件不跟随，可能不完整。
  - 本脚本不执行 workspace。执行只经 live/mcp_server.py 的 run_workspace
    工具（confirm 闸 + 运行日志留档），避免出现两条执行路径。
  - 服务器场景（发布、调度、治理）请用 Safe Software 官方的 FME Flow
    MCP Server；本包只补"本地桌面授权下直接跑 .fmw 文件"这一窄缝。

设计约束（与系列其他桥一致）：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - 拿不到的字段如实留空并写入 notes，不许猜。
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass


def emit(obj, exit_code=0):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return exit_code


def fail(error_code, message, **extra):
    obj = {"ok": False, "error_code": error_code, "message": message}
    obj.update(extra)
    return emit(obj, exit_code=1)


# ------------------------------------------------------------- FME 探测
def install_candidates():
    """返回 [(来源, 目录)] 形式的 FME 安装候选目录列表。"""
    cands = []
    home = os.environ.get("FME_HOME")
    if home:
        cands.append(("env:FME_HOME", home))
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        for base in (pf, pfx):
            cands.append(("default", os.path.join(base, "FME")))
            for d in sorted(glob.glob(os.path.join(base, "FME*"))):
                if os.path.isdir(d):
                    cands.append(("glob", d))
    cands.append(("default", "/opt/fme"))
    for d in sorted(glob.glob("/opt/fme*")):
        if os.path.isdir(d):
            cands.append(("glob", d))
    seen, out = set(), []
    for src, d in cands:
        if d not in seen:
            seen.add(d)
            out.append((src, d))
    return out


def candidate_status():
    status = []
    for src, d in install_candidates():
        status.append({
            "source": src, "path": d, "exists": os.path.isdir(d),
            "has_fme_exe": any(os.path.isfile(os.path.join(d, n))
                               for n in ("fme.exe", "fme")),
            "has_fmeobjects": any(os.path.exists(os.path.join(d, n))
                                  for n in ("fmeobjects", "fmeobjects.py")),
        })
    return status


def try_import_fmeobjects():
    """返回 (module, error_str)。只做当前解释器内的直接导入。"""
    try:
        import fmeobjects
        return fmeobjects, None
    except Exception as e:
        return None, str(e)


def version_clues(mod):
    clues = []
    if mod is not None:
        for attr in ("__version__", "version", "VERSION"):
            v = getattr(mod, attr, None)
            if v:
                clues.append("fmeobjects.%s=%s" % (attr, v))
    for _src, d in install_candidates():
        if os.path.isdir(d):
            clues.append("install dir: %s" % d)
    return clues


# ---------------------------------------------------------------- preflight
def cmd_preflight(args):
    report = {"ok": True, "action": "preflight", "python": sys.version.split()[0],
              "checks": {}}
    mod, err = try_import_fmeobjects()
    if mod is None:
        report["checks"]["fmeobjects_import"] = "fail: %s" % err
        report["install_candidates"] = candidate_status()
        report["fme_home_env"] = os.environ.get("FME_HOME")
        return fail("FME_NOT_AVAILABLE",
                    "当前解释器无法导入 fmeobjects: %s" % err, report=report)
    report["checks"]["fmeobjects_import"] = "ok"
    report["fmeobjects_file"] = getattr(mod, "__file__", "unknown")
    report["version_clues"] = version_clues(mod)
    report["fme_home_env"] = os.environ.get("FME_HOME")
    report["install_candidates"] = candidate_status()
    runner = getattr(mod, "FMEWorkspaceRunner", None)
    report["checks"]["FMEWorkspaceRunner"] = "ok" if runner is not None else "missing"
    if runner is None:
        return fail("FMEOBJECTS_INCOMPLETE",
                    "fmeobjects 已导入但缺少 FMEWorkspaceRunner", report=report)
    return emit(report)


# ------------------------------------------------------------------- scan
def cmd_scan(args):
    root = args.directory
    if not os.path.isdir(root):
        return fail("DIR_NOT_FOUND", "扫描目录不存在: %s" % root)
    items = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".fmw") and ".bak-" not in fn.lower():
                p = os.path.join(dirpath, fn)
                st = os.stat(p)
                items.append({
                    "name": fn, "path": p, "bytes": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                })
    items.sort(key=lambda x: x["path"])
    return emit({"ok": True, "action": "scan", "directory": root,
                 "count": len(items), "workspaces": items})


# ------------------------------------------------------------------- info
_RE_DATASET = re.compile(r'^\s*([A-Za-z0-9_]+)_DATASET\s+"?([^"\r\n]+?)"?\s*$')
_RE_FACTORY = re.compile(r'FACTORY_DEF\s+\*?\s*([A-Za-z0-9_]+)')
_RE_FACTORY_NAME = re.compile(r'FACTORY_NAME\s+"([^"]+)"|FACTORY_NAME\s+(\S+)')
_RE_KW = r'%s_KEYWORD\s+(\S+)'


def _keyword_set(text, kind):
    return {m.group(1).upper() for m in re.finditer(_RE_KW % kind, text)}


def _matches(prefix, keywords):
    for k in keywords:
        if prefix == k or k.startswith(prefix + "_") or prefix.startswith(k):
            return True
    return False


def parse_fmw_text(text):
    """对 .fmw 文本做尽力解析，返回 (datasets, transformers, header)。"""
    readers = _keyword_set(text, "READER")
    writers = _keyword_set(text, "WRITER")
    sources, targets, other = [], [], []
    for line in text.splitlines():
        m = _RE_DATASET.match(line)
        if not m:
            continue
        prefix, ds = m.group(1).upper(), m.group(2).strip()
        entry = {"format_keyword": prefix, "dataset": ds}
        if _matches(prefix, readers):
            sources.append(entry)
        elif _matches(prefix, writers):
            targets.append(entry)
        else:
            other.append(entry)
    by_factory = {}
    names = []
    total = 0
    for line in text.splitlines():
        fm = _RE_FACTORY.search(line)
        if fm:
            by_factory[fm.group(1)] = by_factory.get(fm.group(1), 0) + 1
            total += 1
        nm = _RE_FACTORY_NAME.search(line)
        if nm:
            names.append(nm.group(1) or nm.group(2))
    header = {}
    tm = re.search(r'TITLE\s*=\s*"([^"]+)"', text)
    if tm:
        header["title"] = tm.group(1)
    bm = re.search(r'FME_BASE_BUILD_NUM\s+"?(\d+)"?', text)
    if bm:
        header["fme_base_build_num"] = bm.group(1)
    return ({"sources": sources, "targets": targets, "other": other},
            {"factory_instances_total": total, "by_factory": by_factory,
             "factory_names_sample": names[:20]},
            header)


def parse_fmw_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    datasets, transformers, header = parse_fmw_text(text)
    return {"mode": "file-parse", "complete": False,
            "bytes": len(raw), "lines": text.count("\n") + 1,
            "header": header, "datasets": datasets,
            "transformers": transformers,
            "notes": ["mode=file-parse：从 .fmw 文本尽力解析，可能不完整；"
                      "宏 $(...) 未展开、INCLUDE 文件未跟随、注释行中的伪指令可能误计",
                      "数据集路径以原文为准，未校验其真实存在性"]}


def cmd_info(args):
    path = args.workspace
    if not os.path.isfile(path):
        return fail("FILE_NOT_FOUND", "workspace 文件不存在: %s" % path)
    try:
        result = parse_fmw_file(path)
    except Exception as e:
        return fail("PARSE_FAILED", "解析失败: %s" % e)
    result.update({"ok": True, "action": "info", "path": path})
    return emit(result)


# ----------------------------------------------------------------- backup
def cmd_backup(args):
    src = args.workspace
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "workspace 文件不存在: %s" % src)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root, ext = os.path.splitext(src)
    dst = "%s.bak-%s%s" % (root, stamp, ext)
    if os.path.exists(dst):
        return fail("BACKUP_EXISTS", "目标备份已存在，拒绝覆盖: %s" % dst)
    shutil.copy2(src, dst)
    h = hashlib.sha256()
    with open(dst, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return emit({"ok": True, "action": "backup", "source": src, "backup": dst,
                 "bytes": os.path.getsize(dst), "sha256": h.hexdigest()})


def main():
    p = argparse.ArgumentParser(prog="fme_bridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preflight")
    pp.set_defaults(func=cmd_preflight)
    sp = sub.add_parser("scan")
    sp.add_argument("directory")
    sp.set_defaults(func=cmd_scan)
    ip = sub.add_parser("info")
    ip.add_argument("workspace")
    ip.set_defaults(func=cmd_info)
    bp = sub.add_parser("backup")
    bp.add_argument("workspace")
    bp.set_defaults(func=cmd_backup)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
