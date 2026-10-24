#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_project.py —— Global Mapper 工程盘点 / 迁移验收（只读）。

盘点逻辑与 gm_bridge.py 的 inspect 对齐，分两层：
  1) 纯 Python 层（不依赖 Global Mapper）：工程文件本身（大小 / sha256）、
     .gmw 文本片段解析出的被引用数据文件及其存在性、同主名伴生文件清单、
     被引用 .shp 的伴生完整性（.shx/.dbf 必需，.prj/.cpg 可选）。
  2) 模块层（必须依赖 globalmapper 模块，仅随 Global Mapper Pro 提供）：
     把工程复制到临时目录后用模块打开副本枚举图层。模块缺失时不裸奔：
     顶层输出 {"ok": false, "error": "GM_MODULE_NOT_AVAILABLE", ...}
     并以退出码 1 结束；纯 Python 层的盘点结果仍附在输出里。
     本脚本不会拿 traceback 当报错。

--copy-to <dir>：先把工程文件 + 同主名伴生文件 + 被引用数据文件的
伴生集复制到新目录，再对副本重新盘点，用于验收“换目录后还能不能打开、
引用是否还完整”。目标目录已存在时结构化报错，不覆盖。

用法：
  python verify_project.py --workspace project.gmw
  python verify_project.py --workspace project.gmw --copy-to <新目录>

退出码：0=盘点完成（问题见 issues 列表）；1=硬错误（文件不存在 /
复制目标已存在 / globalmapper 模块不可用 / 未预期异常，均结构化回报）。
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 注意：不要在本脚本里另行重包 sys.stdout——gm_bridge 在导入时已重包一次，
# 二次重包会让先前的 wrapper 被回收时关掉底层 buffer（实测 I/O operation
# on closed file）。因此桥模块在顶层先导入，且只导入这一次。
try:
    import gm_bridge
    _BRIDGE_IMPORT_ERROR = None
except Exception as _e:  # 导入失败也要结构化回报，不裸 traceback
    gm_bridge = None
    _BRIDGE_IMPORT_ERROR = _e

# 伴生文件：同主名、下列扩展名视为一组，必须成套搬运/校验
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
    """某数据文件的同主名伴生集现状：{ext: exists}。"""
    stem, _ext = os.path.splitext(file_path)
    found = {}
    for ext in sorted(COMPANION_EXTS):
        cand = stem + ext
        if os.path.isfile(cand):
            found[ext] = True
    return found


def _check_shp_companions(shp_path, issues, label):
    comp = _companions(shp_path)
    for ext in SHP_REQUIRED:
        if ext not in comp:
            issues.append("%s 缺少必需伴生文件 %s%s" % (label, os.path.splitext(shp_path)[0], ext))
    return comp


def _same_stem_siblings(project):
    src_dir = os.path.dirname(os.path.abspath(project))
    stem = os.path.splitext(os.path.basename(project))[0]
    out = []
    try:
        for name in sorted(os.listdir(src_dir)):
            full = os.path.join(src_dir, name)
            if os.path.isfile(full) and os.path.splitext(name)[0] == stem \
                    and name != os.path.basename(project):
                out.append(name)
    except Exception:
        pass
    return out


def pure_inventory(project, gm_bridge, issues):
    """纯 Python 层盘点：不依赖 globalmapper 模块。"""
    src_dir = os.path.dirname(os.path.abspath(project))
    inv = {"bytes": os.path.getsize(project), "sha256": _sha256(project)}
    parsed = gm_bridge._partial_parse_gmw(project)
    inv["gmw_header"] = parsed["header"]
    inv["looks_like_gm_workspace"] = parsed["looks_like_gm_workspace"]
    if not parsed["looks_like_gm_workspace"]:
        issues.append("文件头未见 GLOBAL_MAPPER 标记，可能不是 .gmw 或版本格式有变")
    refs = []
    for ref in parsed["filenames"]:
        cand = ref if os.path.isabs(ref) else os.path.join(src_dir, ref)
        entry = {"ref": ref, "resolved": cand, "exists": os.path.exists(cand)}
        if not entry["exists"]:
            issues.append("被引用数据文件不存在: %s" % ref)
        elif cand.lower().endswith(".shp"):
            entry["companions"] = _check_shp_companions(cand, issues, "数据文件 %s" % ref)
            for ext in SHP_OPTIONAL:
                if ext not in entry["companions"]:
                    entry.setdefault("companions_missing_optional", []).append(ext)
        refs.append(entry)
    inv["referenced_files"] = refs
    inv["same_stem_siblings"] = _same_stem_siblings(project)
    for sib in inv["same_stem_siblings"]:
        if sib.lower().endswith(".shp"):
            _check_shp_companions(os.path.join(src_dir, sib), issues,
                                  "同主名伴生 %s" % sib)
    inv["layer_name_guesses"] = parsed["layer_name_guesses"]
    return inv


def module_inventory(project, gm_bridge, issues):
    """模块层盘点：复制到临时目录后用 globalmapper 模块打开副本枚举图层。
    返回 (module_section, hard_error_or_None)。"""
    mod, err = gm_bridge._import_gm()
    if mod is None:
        return ({"ok": False, "error": "GM_MODULE_NOT_AVAILABLE",
                 "message": "globalmapper 模块不可用: %s；图层级盘点需要 "
                            "Global Mapper Pro 的 Python 模块" % err},
                "GM_MODULE_NOT_AVAILABLE")
    notes = []
    tmpdir = tempfile.mkdtemp(prefix="gmverify-")
    try:
        work_copy = os.path.join(tmpdir, os.path.basename(project))
        shutil.copy2(project, work_copy)
        src_dir = os.path.dirname(os.path.abspath(project))
        stem = os.path.splitext(os.path.basename(project))[0]
        try:
            for name in os.listdir(src_dir):
                if name == os.path.basename(project):
                    continue
                full = os.path.join(src_dir, name)
                if os.path.isfile(full) and os.path.splitext(name)[0] == stem:
                    shutil.copy2(full, os.path.join(tmpdir, name))
        except Exception:
            pass
        result = gm_bridge._inspect_via_module(mod, work_copy, notes)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if result is None:
        issues.append("模块在位但未能枚举图层（见 module_inventory.notes），"
                      "图层清单只能以纯 Python 层的名称推测为准")
        return {"ok": False, "error": "MODULE_ENUM_EMPTY", "notes": notes}, None
    result = dict(result)
    result["ok"] = True
    result["notes"] = notes
    return result, None


def copy_project_tree(project, dest, gm_bridge):
    """复制工程 + 同主名伴生 + 被引用同目录数据文件的伴生集到 dest。
    返回 (副本工程路径, 已复制文件名列表)。dest 须不存在（调用方已校验）。"""
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
    # 被引用且位于工程同目录的数据文件：连同其同主名伴生集一起复制
    parsed = gm_bridge._partial_parse_gmw(project)
    for ref in parsed["filenames"]:
        cand = ref if os.path.isabs(ref) else os.path.join(src_dir, ref)
        if os.path.isfile(cand) and os.path.dirname(os.path.abspath(cand)) == src_dir:
            _copy(cand)
            ref_stem = os.path.splitext(cand)[0]
            for ext in sorted(COMPANION_EXTS):
                sib = ref_stem + ext
                if os.path.isfile(sib):
                    _copy(sib)
    return os.path.join(dest, os.path.basename(project)), copied


def run(args):
    if gm_bridge is None:
        print(json.dumps({"ok": False, "error": "GM_BRIDGE_IMPORT_FAILED",
                          "message": str(_BRIDGE_IMPORT_ERROR)},
                         ensure_ascii=False))
        return 1
    project = args.workspace
    if not os.path.isfile(project):
        print(json.dumps({"ok": False, "error": "FILE_NOT_FOUND",
                          "message": "工程文件不存在: %s" % project},
                         ensure_ascii=False))
        return 1
    copied_files = None
    if args.copy_to:
        if os.path.exists(args.copy_to):
            print(json.dumps({"ok": False, "error": "COPY_TARGET_EXISTS",
                              "message": "目标已存在，拒绝覆盖: %s" % args.copy_to},
                             ensure_ascii=False))
            return 1
        project, copied_files = copy_project_tree(project, args.copy_to, gm_bridge)

    issues = []
    out = {"action": "verify_project",
           "workspace": os.path.abspath(project),
           "copied_to": args.copy_to, "copied_files": copied_files,
           "issues": issues}
    out["file"] = pure_inventory(project, gm_bridge, issues)
    module_section, hard_error = module_inventory(project, gm_bridge, issues)
    out["module_inventory"] = module_section
    if hard_error:
        out["ok"] = False
        out["error"] = hard_error
        out["message"] = module_section.get("message")
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
    ap.add_argument("--workspace", required=True, help=".gmw 工程文件路径")
    ap.add_argument("--copy-to", default=None, help="先复制工程+伴生到新目录再盘点副本")
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
