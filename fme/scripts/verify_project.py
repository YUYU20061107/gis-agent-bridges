#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_project.py —— FME workspace 盘点 / 迁移验收（只读）。

盘点逻辑与 fme_bridge.py 的 info 对齐，分两层：
  1) 纯 Python 层（不依赖 FME）：.fmw 本质是文本，直接解析提取
     源/目标数据集与 transformer 信息（mode=file-parse、complete=false，
     宏 $(...) 不展开、INCLUDE 不跟随，可能不完整）；同时校验数据集
     路径的存在性与 .shp 数据集的伴生完整性（.shx/.dbf 必需，
     .prj/.cpg 可选）。含宏的数据集路径无法在静态盘点中定论，
     exists 记为 null 并写进 issues，不猜。
  2) FME 层（必须依赖 fmeobjects）：校验当前解释器能否导入
     fmeobjects 且 FMEWorkspaceRunner 在位——这是“本机具备运行该
     workspace 的前提”的盘点项。缺失时不裸奔：顶层输出
     {"ok": false, "error": "FME_NOT_AVAILABLE", ...} 并以退出码 1
     结束，纯 Python 层的盘点结果仍附在输出里。绝不输出 traceback。

本脚本不运行 workspace（执行只经 live/mcp_server.py 的 run_workspace，
见 SKILL.md 的唯一执行路径纪律）；服务器场景请用官方 FME Flow MCP。

--copy-to <dir>：先把 .fmw + 同主名伴生文件 + 同目录被引用 .shp 数据集
的伴生集复制到新目录，再对副本重新盘点。目标目录已存在时结构化报错。

用法：
  python verify_project.py --workspace job.fmw
  python verify_project.py --workspace job.fmw --copy-to <新目录>

退出码：0=盘点完成（问题见 issues 列表）；1=硬错误（文件不存在 /
复制目标已存在 / FME 不可用 / 未预期异常，均结构化回报）。
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 注意：不要在本脚本里另行重包 sys.stdout——fme_bridge 在导入时已重包一次，
# 二次重包会让先前的 wrapper 被回收时关掉底层 buffer（实测 I/O operation
# on closed file）。因此桥模块在顶层先导入，且只导入这一次。
try:
    import fme_bridge
    _BRIDGE_IMPORT_ERROR = None
except Exception as _e:  # 导入失败也要结构化回报，不裸 traceback
    fme_bridge = None
    _BRIDGE_IMPORT_ERROR = _e

COMPANION_EXTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx",
                  ".shp.xml", ".hdr", ".qpj", ".fix"}
SHP_REQUIRED = [".shx", ".dbf"]
SHP_OPTIONAL = [".prj", ".cpg"]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _companions(file_path):
    stem, _ext = os.path.splitext(file_path)
    return {ext: True for ext in sorted(COMPANION_EXTS)
            if os.path.isfile(stem + ext)}


def _check_dataset(entry, fmw_dir, issues, role):
    """给一个数据集条目补 exists / 伴生信息；宏路径不下结论。"""
    ds = entry.get("dataset") or ""
    checked = dict(entry)
    if "$(" in ds or "${" in ds:
        checked["exists"] = None
        issues.append("%s 数据集含宏、静态盘点无法确认存在性: %s" % (role, ds))
        return checked
    cand = ds if os.path.isabs(ds) else os.path.join(fmw_dir, ds)
    checked["resolved"] = cand
    checked["exists"] = os.path.exists(cand)
    if not checked["exists"]:
        issues.append("%s 数据集不存在: %s" % (role, ds))
    elif cand.lower().endswith(".shp"):
        comp = _companions(cand)
        checked["companions"] = comp
        for ext in SHP_REQUIRED:
            if ext not in comp:
                issues.append("%s 数据集 %s 缺少必需伴生文件 %s%s"
                              % (role, ds, os.path.splitext(cand)[0], ext))
        missing_opt = [e for e in SHP_OPTIONAL if e not in comp]
        if missing_opt:
            checked["companions_missing_optional"] = missing_opt
    return checked


def pure_inventory(project, fme_bridge, issues):
    fmw_dir = os.path.dirname(os.path.abspath(project))
    parsed = fme_bridge.parse_fmw_file(project)
    inv = {"bytes": os.path.getsize(project), "sha256": _sha256(project),
           "mode": parsed["mode"], "complete": parsed["complete"],
           "lines": parsed["lines"], "header": parsed["header"],
           "transformers": parsed["transformers"],
           "notes": parsed["notes"]}
    ds = parsed["datasets"]
    inv["datasets"] = {
        "sources": [_check_dataset(e, fmw_dir, issues, "源") for e in ds["sources"]],
        "targets": [_check_dataset(e, fmw_dir, issues, "目标") for e in ds["targets"]],
        "other": [_check_dataset(e, fmw_dir, issues, "未分类") for e in ds["other"]],
    }
    if not ds["sources"]:
        issues.append("未解析到源数据集（文本解析局限或 workspace 无 reader）")
    if not ds["targets"]:
        issues.append("未解析到目标数据集（文本解析局限或 workspace 无 writer）")
    stem = os.path.splitext(os.path.basename(project))[0]
    siblings = []
    try:
        for name in sorted(os.listdir(fmw_dir)):
            full = os.path.join(fmw_dir, name)
            if os.path.isfile(full) and os.path.splitext(name)[0] == stem \
                    and name != os.path.basename(project):
                siblings.append(name)
    except Exception:
        pass
    inv["same_stem_siblings"] = siblings
    return inv


def fme_availability(fme_bridge):
    """FME 层盘点：fmeobjects 可导入且 runner 在位才算具备运行前提。"""
    mod, err = fme_bridge.try_import_fmeobjects()
    if mod is None:
        return ({"ok": False, "error": "FME_NOT_AVAILABLE",
                 "message": "当前解释器无法导入 fmeobjects: %s" % err,
                 "install_candidates": fme_bridge.candidate_status()},
                "FME_NOT_AVAILABLE")
    runner = getattr(mod, "FMEWorkspaceRunner", None)
    if runner is None:
        return ({"ok": False, "error": "FMEOBJECTS_INCOMPLETE",
                 "message": "fmeobjects 已导入但缺少 FMEWorkspaceRunner",
                 "fmeobjects_file": getattr(mod, "__file__", "unknown")},
                "FMEOBJECTS_INCOMPLETE")
    return ({"ok": True, "fmeobjects_file": getattr(mod, "__file__", "unknown"),
             "version_clues": fme_bridge.version_clues(mod),
             "runner_methods": sorted(n for n in dir(runner)
                                      if not n.startswith("_"))},
            None)


def copy_project_tree(project, dest, fme_bridge):
    """复制 .fmw + 同主名伴生 + 同目录被引用 .shp 的伴生集到 dest。"""
    src_dir = os.path.dirname(os.path.abspath(project))
    os.makedirs(dest)
    copied = []

    def _copy(full):
        name = os.path.basename(full)
        target = os.path.join(dest, name)
        if not os.path.exists(target):
            shutil.copy2(full, target)
            copied.append(name)

    _copy(project)
    stem = os.path.splitext(os.path.basename(project))[0]
    for name in sorted(os.listdir(src_dir)):
        full = os.path.join(src_dir, name)
        if os.path.isfile(full) and os.path.splitext(name)[0] == stem:
            _copy(full)
    parsed = fme_bridge.parse_fmw_file(project)
    for group in ("sources", "targets", "other"):
        for entry in parsed["datasets"][group]:
            ds = entry.get("dataset") or ""
            if "$(" in ds:
                continue
            cand = ds if os.path.isabs(ds) else os.path.join(src_dir, ds)
            if os.path.isfile(cand) \
                    and os.path.dirname(os.path.abspath(cand)) == src_dir \
                    and cand.lower().endswith(".shp"):
                _copy(cand)
                shp_stem = os.path.splitext(cand)[0]
                for ext in sorted(COMPANION_EXTS):
                    sib = shp_stem + ext
                    if os.path.isfile(sib):
                        _copy(sib)
    return os.path.join(dest, os.path.basename(project)), copied


def run(args):
    if fme_bridge is None:
        print(json.dumps({"ok": False, "error": "FME_BRIDGE_IMPORT_FAILED",
                          "message": str(_BRIDGE_IMPORT_ERROR)},
                         ensure_ascii=False))
        return 1
    project = args.workspace
    if not os.path.isfile(project):
        print(json.dumps({"ok": False, "error": "FILE_NOT_FOUND",
                          "message": "workspace 文件不存在: %s" % project},
                         ensure_ascii=False))
        return 1
    copied_files = None
    if args.copy_to:
        if os.path.exists(args.copy_to):
            print(json.dumps({"ok": False, "error": "COPY_TARGET_EXISTS",
                              "message": "目标已存在，拒绝覆盖: %s" % args.copy_to},
                             ensure_ascii=False))
            return 1
        project, copied_files = copy_project_tree(project, args.copy_to, fme_bridge)

    issues = []
    out = {"action": "verify_project",
           "workspace": os.path.abspath(project),
           "copied_to": args.copy_to, "copied_files": copied_files,
           "issues": issues}
    out["file"] = pure_inventory(project, fme_bridge, issues)
    fme_section, hard_error = fme_availability(fme_bridge)
    out["fme_availability"] = fme_section
    if hard_error:
        out["ok"] = False
        out["error"] = hard_error
        out["message"] = fme_section.get("message")
        text = json.dumps(out, ensure_ascii=False, indent=1)
        print(text)
        if args.json_out:
            io.open(args.json_out, "w", encoding="utf-8").write(text)
        return 1
    out["ok"] = True
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if args.json_out:
        io.open(args.json_out, "w", encoding="utf-8").write(text)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="verify_project")
    ap.add_argument("--workspace", required=True, help=".fmw workspace 路径")
    ap.add_argument("--copy-to", default=None, help="先复制 workspace+伴生到新目录再盘点副本")
    ap.add_argument("--json-out", default=None, help="同时把 JSON 写到该文件")
    args = ap.parse_args()
    try:
        return run(args)
    except Exception as e:  # 绝不裸 traceback：一切异常结构化回报
        print(json.dumps({"ok": False, "error": "VERIFY_FAILED",
                          "message": "%s: %s" % (type(e).__name__, e)},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
