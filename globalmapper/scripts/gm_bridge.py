# -*- coding: utf-8 -*-
"""
gm_bridge.py — Global Mapper 工程文件桥接脚本（v0.1，无头为主，只读优先）

子命令：
  preflight  环境预检：定位 globalmapper Python 模块（仅 Global Mapper Pro 提供）
             与安装线索，回报版本候选命中情况
  backup     备份工作区文件（.gmw，时间戳副本 + sha256），并提示同名数据文件
             与工作区引用的外部数据文件是否存在
  inspect    工程盘点：优先用 globalmapper 模块打开工作区副本列图层；
             模块不可用或枚举不到图层时退化为解析 .gmw 可读文本片段
             （mode=headless-partial-parse，结果可能不完整，如实标注）

设计约束（与本系列其他桥一致）：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - inspect 永不直接以写方式接触原件：模块路线先把工作区（及同名数据）
    复制到临时目录再打开；文本解析路线只读原件字节。
  - globalmapper 模块的 API 在不同大版本间命名/签名差异大：一律多策略尝试，
    命中的函数名记入输出的 via / opened_via 字段，供维护者据实收紧。
    拿不准的签名绝不写死假装确定。
  - 本脚本不包含任何写业务动作（不 save、不删、不改图层）。
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
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


# ------------------------------------------------------------ API 候选表
# globalmapper 模块函数名随版本差异大，以下均为“候选”，运行时逐个试探并
# 回报命中者；未命中不等于函数不存在（可能改名或在 SDK 侧），以 probe 结果为准。
VERSION_ATTRS = ["__version__", "VERSION", "version"]
VERSION_FUNCS = ["GM_GetVersion", "GM_GetVersionInfo", "GM_GetGlobalMapperVersion",
                 "GM_GetProductVersion", "GetVersion"]
LOAD_FUNCS = ["GM_LoadWorkspace", "GM_LoadLayer", "GM_LoadLayerList",
              "GM_OpenWorkspace", "GM_LoadLayers"]
LAYER_LIST_FUNCS = ["GM_GetLayerList", "GM_GetLoadedLayerList", "GM_GetAllLayers",
                    "GM_ListLayers", "GM_GetLayers"]
LAYER_INFO_FUNCS = ["GM_GetLayerInfo", "GM_GetLayerDescription", "GM_GetLayerName"]
LAYER_NAME_ATTRS = ["m_strName", "Name", "name", "m_strDesc", "Description",
                    "description", "m_strFilename", "Filename", "filename"]
CLOSE_FUNCS = ["GM_CloseLayer", "GM_UnloadLayer", "GM_CloseAllLayers",
               "GM_UnloadAllLayers"]

INSTALL_ENV_VARS = ["GM_INSTALL_DIR", "GLOBALMAPPER_HOME", "GLOBAL_MAPPER_HOME",
                    "GM_HOME"]
INSTALL_DIR_GLOBS = [
    r"C:\Program Files\GlobalMapper*",
    r"C:\Program Files (x86)\GlobalMapper*",
    "/Applications/Global Mapper*",
]


# ------------------------------------------------------------------ helpers
def _try_attrs(obj, names):
    """按顺序尝试属性/方法，返回 (值, 命中的名字)；方法会自动调用（无参）。"""
    for name in names:
        if obj is None or not hasattr(obj, name):
            continue
        val = getattr(obj, name)
        try:
            if callable(val):
                val = val()
            return val, name
        except Exception:
            continue
    return None, None


def _safe_str(v):
    try:
        return str(v)
    except Exception:
        return None


def _call_first(mod, names, *args):
    """按候选顺序调用模块函数，返回 (结果, 命中函数名, 尝试记录列表)。"""
    attempts = []
    for name in names:
        fn = getattr(mod, name, None)
        if not callable(fn):
            attempts.append("%s: not present" % name)
            continue
        try:
            return fn(*args), name, attempts
        except Exception as e:
            attempts.append("%s: %s" % (name, e))
    return None, None, attempts


def _flatten_handles(result):
    """把图层枚举结果尽量摊平成 handle 列表；摊不平返回 [] 并保留原始形态说明。"""
    if result is None:
        return [], "none"
    if isinstance(result, (list, tuple)):
        items = [x for x in result if x is not None]
        return items, "sequence(%d)" % len(items)
    return [result], "single:%s" % type(result).__name__


def _layer_name(mod, handle):
    """多策略取图层名，返回 (name, via)。"""
    info, via, _att = _call_first(mod, LAYER_INFO_FUNCS, handle)
    if info is not None:
        if isinstance(info, str):
            return info, via
        for attr in LAYER_NAME_ATTRS:
            if hasattr(info, attr):
                val = getattr(info, attr)
                if callable(val):
                    try:
                        val = val()
                    except Exception:
                        continue
                if val:
                    return _safe_str(val), "%s.%s" % (via, attr)
        return _safe_str(info)[:120], via + "(repr)"
    if isinstance(handle, str):
        return handle, "handle-as-name"
    return None, None


def _module_version(mod):
    """多策略取版本号，返回 (version_str, via)。"""
    for attr in VERSION_ATTRS:
        if hasattr(mod, attr):
            val = getattr(mod, attr)
            if not callable(val) and val:
                return _safe_str(val), "attr:" + attr
    val, via, _att = _call_first(mod, VERSION_FUNCS)
    if val is not None:
        return _safe_str(val)[:120], via
    return None, None


def _install_clues():
    clues = {"env": {}, "dirs_found": []}
    for var in INSTALL_ENV_VARS:
        if os.environ.get(var):
            clues["env"][var] = os.environ[var]
    import glob as _glob
    for pat in INSTALL_DIR_GLOBS:
        for hit in _glob.glob(pat):
            if os.path.isdir(hit):
                clues["dirs_found"].append(hit)
    pf = os.environ.get("ProgramFiles")
    if pf:
        for hit in _glob.glob(os.path.join(pf, "GlobalMapper*")):
            if os.path.isdir(hit) and hit not in clues["dirs_found"]:
                clues["dirs_found"].append(hit)
    return clues


def _import_gm():
    try:
        import globalmapper
        return globalmapper, None
    except Exception as e:
        return None, e


# ---------------------------------------------------------------- preflight
def cmd_preflight(args):
    report = {"ok": True, "action": "preflight", "python": sys.version.split()[0],
              "checks": {}}
    mod, err = _import_gm()
    if mod is None:
        report["checks"]["globalmapper_import"] = "fail"
        report["install_clues"] = _install_clues()
        return fail(
            "GM_MODULE_NOT_AVAILABLE",
            "globalmapper 模块导入失败: %s。"
            "该模块仅随 Global Mapper Pro 提供（标准版无 Python 模块）；"
            "请确认已安装 Pro 版且解释器能找到其模块目录" % err,
            report=report)
    report["checks"]["globalmapper_import"] = "ok"
    report["module_file"] = getattr(mod, "__file__", "unknown")
    version, via = _module_version(mod)
    report["module_version"] = version
    report["module_version_via"] = via
    hits = {}
    for group, cands in (("load", LOAD_FUNCS), ("layer_list", LAYER_LIST_FUNCS),
                         ("layer_info", LAYER_INFO_FUNCS), ("close", CLOSE_FUNCS),
                         ("version", VERSION_FUNCS)):
        hits[group] = [n for n in cands if callable(getattr(mod, n, None))]
    report["function_candidates_hit"] = hits
    report["install_clues"] = _install_clues()
    return emit(report)


# ------------------------------------------------------- .gmw 文本部分解析
_FILENAME_PATTERNS = [
    re.compile(r'FILENAME\s*=\s*"([^"]+)"', re.IGNORECASE),
    re.compile(r"FILE_NAME\s*=\s*\"([^\"]+)\"", re.IGNORECASE),
    re.compile(r"FILENAME\s*=\s*([^\s\"']+)", re.IGNORECASE),
]
_HEADER_HINT = "GLOBAL_MAPPER"


def _partial_parse_gmw(path):
    """只读解析 .gmw 的可读文本片段，尽力提取头部行与被引用的数据文件名。
    .gmw 多为文本格式，但新版本可能含二进制段；解析不到不等于工作区为空，
    调用方必须标注结果可能不完整。"""
    out = {"header": None, "filenames": [], "layer_name_guesses": []}
    try:
        with open(path, "rb") as f:
            raw = f.read(8 * 1024 * 1024)
    except Exception as e:
        out["parse_error"] = str(e)
        return out
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line:
            out["header"] = line[:200]
            break
    seen = []
    for pat in _FILENAME_PATTERNS:
        for m in pat.findall(text):
            if m not in seen:
                seen.append(m)
    out["filenames"] = seen
    out["layer_name_guesses"] = [os.path.basename(p.replace("\\", "/"))
                                 for p in seen]
    out["looks_like_gm_workspace"] = bool(
        out["header"] and _HEADER_HINT in out["header"].upper())
    return out


# ------------------------------------------------------------------- backup
def cmd_backup(args):
    src = args.workspace
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工作区文件不存在: %s" % src)
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
    # 同名数据提示：Global Mapper 工作区只保存引用关系，实际数据多为同目录下
    # 的同名文件/外部文件，只复制 .gmw 不等于把数据一并备份。
    src_dir = os.path.dirname(os.path.abspath(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    siblings = []
    try:
        for name in sorted(os.listdir(src_dir)):
            if name == os.path.basename(src) or ".bak-" in name:
                continue
            if os.path.splitext(name)[0] == stem:
                siblings.append(name)
    except Exception:
        pass
    parsed = _partial_parse_gmw(src)
    referenced = []
    for ref in parsed["filenames"]:
        cand = ref if os.path.isabs(ref) else os.path.join(src_dir, ref)
        referenced.append({"ref": ref, "exists_next_to_workspace": os.path.exists(cand)})
    notes = ["备份只复制工作区文件本身；工作区引用的外部数据未一并复制，"
             "迁移时请连同 referenced_files 中 exists 的文件一起处理"]
    if ext.lower() != ".gmw":
        notes.append("源文件扩展名不是 .gmw（实际为 %s），已按原样备份" % ext)
    return emit({"ok": True, "action": "backup", "source": src, "backup": dst,
                 "bytes": os.path.getsize(dst), "sha256": h.hexdigest(),
                 "same_stem_siblings": siblings,
                 "referenced_files": referenced, "notes": notes})


# ------------------------------------------------------------------ inspect
def _inspect_via_module(mod, work_copy, notes):
    """用 globalmapper 模块打开工作区副本并枚举图层。
    返回 result dict；枚举不到图层时返回 None 让调用方退化到文本解析。"""
    loaded, load_via, attempts = _call_first(mod, LOAD_FUNCS, work_copy)
    notes.extend("load attempt: %s" % a for a in attempts)
    if load_via is None:
        notes.append("全部加载候选均失败，退化到文本解析")
        return None
    handles, shape = _flatten_handles(loaded)
    list_via = None
    if len(handles) <= 1:
        listed, list_via, attempts2 = _call_first(mod, LAYER_LIST_FUNCS)
        notes.extend("layer_list attempt: %s" % a for a in attempts2)
        if listed is not None:
            handles2, shape2 = _flatten_handles(listed)
            if len(handles2) > len(handles):
                handles, shape = handles2, shape2
    if not handles:
        notes.append("模块已加载工作区但图层枚举为空（load 返回形态: %s）" % shape)
        return None
    layers = []
    for i, handle in enumerate(handles):
        name, name_via = _layer_name(mod, handle)
        layers.append({"index": i, "name": name, "name_via": name_via,
                       "handle_repr": _safe_str(handle)[:80]})
    for closer in CLOSE_FUNCS:
        fn = getattr(mod, closer, None)
        if callable(fn):
            try:
                fn()
                break
            except Exception:
                try:
                    for handle in handles:
                        fn(handle)
                    break
                except Exception:
                    continue
    return {"mode": "headless-module", "opened_via": load_via,
            "layer_list_via": list_via, "layers": layers, "complete": True}


def cmd_inspect(args):
    src = args.workspace
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工作区文件不存在: %s" % src)
    notes = []
    mod, err = _import_gm()
    result = None
    if mod is not None:
        tmpdir = tempfile.mkdtemp(prefix="gmbridge-")
        try:
            work_copy = os.path.join(tmpdir, os.path.basename(src))
            shutil.copy2(src, work_copy)
            # 同名数据一并复制到临时目录，尽量让相对引用在副本处可解析
            src_dir = os.path.dirname(os.path.abspath(src))
            stem = os.path.splitext(os.path.basename(src))[0]
            try:
                for name in os.listdir(src_dir):
                    if name == os.path.basename(src):
                        continue
                    full = os.path.join(src_dir, name)
                    if os.path.isfile(full) and os.path.splitext(name)[0] == stem:
                        shutil.copy2(full, os.path.join(tmpdir, name))
            except Exception:
                pass
            result = _inspect_via_module(mod, work_copy, notes)
        except Exception as e:
            notes.append("module inspect failed: %s" % e)
            result = None
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        notes.append("globalmapper 模块不可用: %s" % err)
    if result is None:
        parsed = _partial_parse_gmw(src)
        layers = [{"index": i, "name": nm, "name_via": "gmw-text-parse(basename)"}
                  for i, nm in enumerate(parsed["layer_name_guesses"])]
        result = {"mode": "headless-partial-parse", "opened_via": None,
                  "layers": layers, "complete": False,
                  "gmw_header": parsed["header"],
                  "looks_like_gm_workspace": parsed["looks_like_gm_workspace"],
                  "referenced_files": parsed["filenames"]}
        notes.append("当前为文本部分解析结果：只提取到工作区文本里写明的数据文件名，"
                     "图层名是文件名推测，可能与实际图层名不一致，结果可能不完整")
    result.update({"ok": True, "action": "inspect", "source": src, "notes": notes})
    return emit(result)


def main():
    p = argparse.ArgumentParser(prog="gm_bridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preflight")
    pp.set_defaults(func=cmd_preflight)
    bp = sub.add_parser("backup")
    bp.add_argument("workspace")
    bp.set_defaults(func=cmd_backup)
    ip = sub.add_parser("inspect")
    ip.add_argument("workspace")
    ip.set_defaults(func=cmd_inspect)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
