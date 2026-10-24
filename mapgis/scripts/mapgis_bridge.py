# -*- coding: utf-8 -*-
"""
mapgis_bridge.py — MapGIS 工程桥接脚本（v0.1，探针优先的骨架实现）

子命令：
  preflight  环境预检：直接调用 probe_mapgis 的探测逻辑，结果原样输出
  backup     备份 .MPJ 工程文件及同名数据文件（时间戳副本 + sha256），纯标准库
  inspect    工程盘点：仅当探针证实存在可用 Python SDK 时，按候选 API 多策略
             尝试打开工程；全部策略失败返回结构化 NOT_SUPPORTED 并附探针结果，
             绝不编造盘点结果

设计约束（与本系列其他桥一致）：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - 本脚本不包含任何写业务动作（不 save、不删、不改工程内容）。
  - MapGIS 的 Python API 形态未经证实，inspect 的"多策略"只是对候选入口的
    有限试探；命中策略会记入输出的 opened_via 字段，没命中就如实说不支持。
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_mapgis  # noqa: E402

# probe_mapgis 导入时已把 stdout 包成 UTF-8；同一 buffer 重复包 TextIOWrapper
# 会在先包者被回收时关掉底层流，故此处仅在编码不是 UTF-8 时才包。
if getattr(sys.stdout, "encoding", None) != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
    except Exception:
        pass


# ---- 序列化净化（与 arcmap 已修版同口径） ----
try:
    _TEXT = unicode  # noqa: F821
except NameError:
    _TEXT = str


def _dec(b):
    """bytes -> 文本。解码顺序：UTF-8 -> 系统文件系统编码 -> GBK -> latin-1。"""
    if isinstance(b, _TEXT):
        return b
    if not isinstance(b, (bytes, bytearray)):
        return "%s" % (b,)
    try:
        return bytes(b).decode("utf-8")
    except Exception:
        pass
    for enc in (sys.getfilesystemencoding(), "gbk", "latin-1"):
        if not enc:
            continue
        try:
            return bytes(b).decode(enc)
        except Exception:
            continue
    return bytes(b).decode("utf-8", "replace")


def _to_text(obj):
    """递归净化待 JSON 序列化的对象：dict/list 递归，bytes 解码为文本，
    其余不可序列化的对象转 str，保证 dumps 不会因为厂商 API 返回
    bytes / 异类对象而 TypeError 崩溃。"""
    if isinstance(obj, dict):
        return dict((_to_text(k), _to_text(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [_to_text(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return _dec(obj)
    if obj is None or isinstance(obj, (_TEXT, bool, int, float)):
        return obj
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return "%s" % (obj,)


def emit(obj, exit_code=0):
    sys.stdout.write(json.dumps(_to_text(obj), ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return exit_code


def fail(error_code, message, **extra):
    obj = {"ok": False, "error_code": error_code, "message": message}
    obj.update(extra)
    return emit(obj, exit_code=1)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- preflight
def cmd_preflight(args):
    """预检即探针：MapGIS 环境是否可用，完全取决于探针结论。"""
    probe = probe_mapgis.run_probe()
    if not probe["ok"]:
        return fail("MAPGIS_PYTHON_NOT_FOUND",
                    "探针未找到可用的 MapGIS Python 绑定，预检不通过",
                    probe=probe)
    return emit({"ok": True, "action": "preflight",
                 "python": probe["python"], "probe": probe})


# ------------------------------------------------------------------- backup
def _same_stem_companions(src):
    """同目录下与工程文件同主名的数据文件/目录（.MPJ 常伴随同名数据）。"""
    folder = os.path.dirname(os.path.abspath(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    companions = []
    try:
        entries = sorted(os.listdir(folder))
    except Exception:
        return companions
    for name in entries:
        if name == os.path.basename(src):
            continue
        if os.path.splitext(name)[0] == stem:
            companions.append(os.path.join(folder, name))
    return companions


def cmd_backup(args):
    src = args.project
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工程文件不存在: %s" % src)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root, ext = os.path.splitext(src)
    dst = "%s.bak-%s%s" % (root, stamp, ext)
    if os.path.exists(dst):
        return fail("BACKUP_EXISTS", "目标备份已存在，拒绝覆盖: %s" % dst)
    shutil.copy2(src, dst)
    copied = [{"source": src, "backup": dst, "bytes": os.path.getsize(dst),
               "sha256": sha256_of(dst)}]
    skipped = []
    for comp in _same_stem_companions(src):
        croot, cext = os.path.splitext(comp)
        cdst = "%s.bak-%s%s" % (croot, stamp, cext)
        try:
            if os.path.isdir(comp):
                if os.path.exists(cdst):
                    skipped.append({"source": comp, "reason": "backup exists"})
                    continue
                shutil.copytree(comp, cdst)
                copied.append({"source": comp, "backup": cdst,
                               "bytes": None, "sha256": None,
                               "note": "directory copied as-is"})
            else:
                if os.path.exists(cdst):
                    skipped.append({"source": comp, "reason": "backup exists"})
                    continue
                shutil.copy2(comp, cdst)
                copied.append({"source": comp, "backup": cdst,
                               "bytes": os.path.getsize(cdst),
                               "sha256": sha256_of(cdst)})
        except Exception as e:
            skipped.append({"source": comp, "reason": str(e)})
    return emit({"ok": True, "action": "backup", "source": src,
                 "copied": copied, "skipped": skipped})


# ------------------------------------------------------------------ inspect
def _try_open_project(mod, path, attempts):
    """对候选 API 做有限多策略试探，返回 (对象, 命中的策略名) 或 (None, None)。

    策略均为启发式：模块级 open/load 函数、工程类构造与打开方法。
    命中只说明"某个入口返回了对象"，对象成员面的解读不在 v0.1 范围内。
    """
    mod_names = [n for n in dir(mod) if not n.startswith("_")]
    # 策略 1：模块级函数，名字含 open/load 且含 project/map/mpj 语义
    for name in mod_names:
        low = name.lower()
        if not callable(getattr(mod, name, None)):
            continue
        if ("open" in low or "load" in low) and \
                ("project" in low or "map" in low or "mpj" in low):
            try:
                obj = getattr(mod, name)(path)
                if obj is not None:
                    attempts.append({"strategy": "module_func:%s" % name,
                                     "ok": True})
                    return obj, "module_func:%s" % name
                attempts.append({"strategy": "module_func:%s" % name,
                                 "ok": False, "error": "returned None"})
            except Exception as e:
                attempts.append({"strategy": "module_func:%s" % name,
                                 "ok": False, "error": str(e)})
    # 策略 2：工程类：类名含 Project / MapDocument / Workspace
    for name in mod_names:
        low = name.lower()
        if not ("project" in low or "mapdocument" in low or "workspace" in low):
            continue
        cls = getattr(mod, name, None)
        if not isinstance(cls, type):
            continue
        for ctor_args in ((path,), ()):
            try:
                obj = cls(*ctor_args)
            except Exception as e:
                attempts.append({"strategy": "class:%s%r" % (name, ctor_args),
                                 "ok": False, "error": str(e)})
                continue
            if ctor_args:
                attempts.append({"strategy": "class:%s(path)" % name, "ok": True})
                return obj, "class:%s(path)" % name
            for meth in ("open", "load", "open_project", "openProject"):
                fn = getattr(obj, meth, None)
                if callable(fn):
                    try:
                        fn(path)
                        attempts.append(
                            {"strategy": "class:%s().%s" % (name, meth), "ok": True})
                        return obj, "class:%s().%s" % (name, meth)
                    except Exception as e:
                        attempts.append(
                            {"strategy": "class:%s().%s" % (name, meth),
                             "ok": False, "error": str(e)})
    return None, None


def cmd_inspect(args):
    src = args.project
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工程文件不存在: %s" % src)
    probe = probe_mapgis.run_probe()
    if not probe["ok"]:
        return fail("MAPGIS_PYTHON_NOT_FOUND",
                    "探针未找到可用的 MapGIS Python 绑定，inspect 无法执行",
                    probe=probe)
    mod = probe_mapgis.load_found_module()
    if mod is None:
        return fail("MAPGIS_PYTHON_NOT_FOUND",
                    "探针结论与重新导入不一致，按未找到处理", probe=probe)
    attempts = []
    try:
        obj, strategy = _try_open_project(mod, src, attempts)
    except Exception as e:
        return fail("INSPECT_FAILED", "盘点试探异常: %s" % e, attempts=attempts,
                    traceback_tail=traceback.format_exc()[-500:])
    if obj is None:
        return fail(
            "NOT_SUPPORTED",
            "已导入模块 %s，但全部候选打开策略均失败；该模块的工程 API 形态"
            "与本脚本假设不符。不要据此编造盘点结果，请把探针与尝试清单"
            "回传维护者据实收紧。" % mod.__name__,
            attempts=attempts, probe=probe)
    members = [n for n in dir(obj) if not n.startswith("_")]
    return emit({
        "ok": True, "action": "inspect", "source": src,
        "opened_via": strategy,
        "object_type": str(type(obj)),
        "object_public_members": members[:200],
        "notes": [
            "v0.1 只回报打开入口命中的策略与返回对象的公开成员面，"
            "不解读成员语义、不声称已完成数据盘点；成员级盘点须等实机"
            "探针结论收紧后在 v0.2 实现。",
        ],
        "attempts": attempts,
    })


def main():
    p = argparse.ArgumentParser(prog="mapgis_bridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preflight")
    pp.set_defaults(func=cmd_preflight)
    bp = sub.add_parser("backup")
    bp.add_argument("project")
    bp.set_defaults(func=cmd_backup)
    ip = sub.add_parser("inspect")
    ip.add_argument("project")
    ip.set_defaults(func=cmd_inspect)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
