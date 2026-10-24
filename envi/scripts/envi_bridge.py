# -*- coding: utf-8 -*-
"""
envi_bridge.py — ENVI 栅格无头桥接脚本（v0.1，无头版）

子命令：
  preflight  环境预检（idlpy 可导入性、ENVI/IDL 安装线索、本机 python）
  inventory  影像盘点：纯 Python 解析 ENVI .hdr 头文件，不依赖 ENVI 本体；
             接受单个 .hdr / 栅格数据文件 / 目录（批量扫描 *.hdr）
  backup     备份栅格文件对（数据文件 + .hdr），时间戳副本 + sha256，纯标准库

设计约束：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - ENVI 栅格的 .hdr 是纯文本头文件（samples/lines/bands、data type、
    interleave、map info、wavelength、band names 等），纯 Python 即可解析；
    这是本桥的立足点：没有 ENVI 许可的机器也能做影像盘点。
  - 本脚本不包含任何写业务动作（不改影像、不删文件）；backup 只生成新副本。
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
from datetime import datetime

def _wrap_stdout():
    # 注意：只许在作为脚本运行时调用。被 probe_api.py 等其他模块 import 时
    # 重复包装同一 buffer 会导致先前的 TextIOWrapper 被回收并关闭底层流。
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
    except Exception:
        pass


# ENVI data type 代码 -> (名称, 每元素字节数)；0/未知给出 None
ENVI_DTYPES = {
    1: ("byte", 1), 2: ("int16", 2), 3: ("int32", 4), 4: ("float32", 4),
    5: ("float64", 8), 6: ("complex64", 8), 9: ("complex128", 16),
    12: ("uint16", 2), 13: ("uint32", 4), 14: ("int64", 8), 15: ("uint64", 8),
}

DATA_EXTS = (".dat", ".img", ".raw", ".bin", ".tif", ".tiff", "")


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


# ---- PathGuard-lite -------------------------------------------------------
# 路径入口校验（main() 分发前统一执行，拒绝时返回 PATH_GUARD_REJECTED）：
#   1) 拒绝 UNC 路径（以双反斜杠或 // 开头）与含 NUL/控制字符的路径；
#   2) 写类参数（_PG_WRITE_ATTRS）的目标路径与任一源路径
#      （_PG_SOURCE_ATTRS 及 layers 列表项）经 realpath+abspath+normcase
#      解析后相同则拒绝，防止把写目标指回原件。其余命令的写目标由脚本
#      按时间戳/固定名派生、不接受调用方指定，不在本条范围。
_PG_SOURCE_ATTRS = ("workspace", "project", "document", "raster", "target",
                    "directory", "image", "points", "spec", "template")
_PG_WRITE_ATTRS = ("out", "export_png")
_PG_LIST_SOURCE_ATTRS = ("layers",)


def _pg_resolve(p):
    try:
        p = _dec(p)
    except Exception:
        pass
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def _pg_check_one(p):
    """单个路径字符串校验，返回违规说明或 None。"""
    if p is None:
        return None
    try:
        s = _dec(p)
    except Exception:
        s = p
    if not isinstance(s, _TEXT):
        s = "%s" % (s,)
    if s.startswith("\\\\") or s.startswith("//"):
        return "UNC 路径不接受: %s" % s
    for ch in s:
        if ord(ch) < 32:
            return "路径含控制字符: %r" % s
    return None


def _path_guard(args):
    """返回违规说明或 None；违规由 main() 以 PATH_GUARD_REJECTED 结构化拒绝。"""
    singles = []
    for attr in _PG_SOURCE_ATTRS + _PG_WRITE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, _TEXT) or isinstance(v, bytes):
            singles.append(v)
    listed = []
    for attr in _PG_LIST_SOURCE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, _TEXT) or isinstance(item, bytes):
                    listed.append(item)
    for v in singles + listed:
        bad = _pg_check_one(v)
        if bad:
            return bad
    sources = []
    for attr in _PG_SOURCE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, _TEXT) or isinstance(v, bytes):
            sources.append(v)
    sources.extend(listed)
    for attr in _PG_WRITE_ATTRS:
        v = getattr(args, attr, None)
        if isinstance(v, _TEXT) or isinstance(v, bytes):
            rv = _pg_resolve(v)
            for s in sources:
                if rv == _pg_resolve(s):
                    return "写目标与源路径相同，拒绝覆盖原件: %s" % v
    return None


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ==== HDR-SHARED-BEGIN ======================================================
# ENVI .hdr 解析的共享实现，与本包另一侧桥中的同名块保持逐字一致：
# 两侧运行形态不同（命令行脚本 / MCP 服务端），无法互相 import，
# 只能以内联副本同步维护。修改任一侧后必须同步另一侧。
def parse_hdr_text(text):
    """解析 .hdr 文本，返回 {key: value} 原始字典。

    .hdr 是 'key = value' 行集合（第一行通常是 'ENVI'），value 可以是
    {a, b, c} 形式且可跨多行；description 里也可能出现逗号与等号，
    因此按花括号深度逐字符切分，不能简单逐行 split。
    """
    body = text.strip()
    if body[:4].upper() == "ENVI":
        nl = body.find("\n")
        body = body[nl + 1:] if nl >= 0 else ""
    fields = {}
    i, n = 0, len(body)
    while i < n:
        # 扫描一个 key
        start = i
        while i < n and body[i] not in "=\n":
            i += 1
        if i >= n or body[i] != "=":
            break
        key = body[start:i].strip().lower()
        i += 1
        # 跳过等号后的空白
        while i < n and body[i] in " \t":
            i += 1
        if i < n and body[i] == "{":
            depth = 0
            vstart = i
            while i < n:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            raw = body[vstart:i]
        else:
            vstart = i
            while i < n and body[i] != "\n":
                i += 1
            raw = body[vstart:i].strip()
        if key:
            fields[key] = raw
        # 跳过行尾与空行
        while i < n and body[i] in "\r\n":
            i += 1
    return fields


def _brace_items(raw):
    """'{a, b, c}' -> ['a', 'b', 'c']；非花括号原样返回单元素列表。"""
    s = (raw or "").strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return [part.strip() for part in s.split(",") if part.strip() != ""]


def _to_int(v):
    try:
        return int(float(v))
    except Exception:
        return None


def _to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def hdr_summary(hdr_path):
    """读 .hdr 并生成结构化盘点条目；失败抛异常由调用方转结构化错误。"""
    with open(hdr_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if "samples" not in text.lower():
        raise ValueError("不是 ENVI .hdr 文件（缺少 samples 字段）: %s" % hdr_path)
    fields = parse_hdr_text(text)
    samples = _to_int(fields.get("samples"))
    lines = _to_int(fields.get("lines"))
    bands = _to_int(fields.get("bands"))
    dtype_code = _to_int(fields.get("data type"))
    dtype_name, dtype_bytes = ENVI_DTYPES.get(dtype_code, (None, None))
    wavelength = [_to_float(x) for x in _brace_items(fields.get("wavelength", ""))]
    entry = {
        "hdr": hdr_path,
        "description": (fields.get("description") or "").strip().strip("{}").strip() or None,
        "samples": samples,
        "lines": lines,
        "bands": bands,
        "data_type_code": dtype_code,
        "data_type": dtype_name,
        "interleave": (fields.get("interleave") or "").strip().lower() or None,
        "byte_order": _to_int(fields.get("byte order")),
        "header_offset": _to_int(fields.get("header offset")),
        "file_type": (fields.get("file type") or "").strip() or None,
        "sensor_type": (fields.get("sensor type") or "").strip() or None,
        "map_info": [x for x in _brace_items(fields.get("map info", ""))] or None,
        "band_names": _brace_items(fields.get("band names", "")) or None,
        "wavelength": wavelength or None,
        "wavelength_units": (fields.get("wavelength units") or "").strip() or None,
    }
    if None not in (samples, lines, bands) and dtype_bytes:
        entry["expected_data_bytes"] = samples * lines * bands * dtype_bytes
    else:
        entry["expected_data_bytes"] = None
    # 找同名数据文件并核对实际大小
    data_path = find_data_file(hdr_path)
    entry["data_file"] = data_path
    if data_path and os.path.isfile(data_path):
        entry["data_bytes"] = os.path.getsize(data_path)
        exp = entry["expected_data_bytes"]
        off = entry["header_offset"] or 0
        entry["size_matches"] = (exp is not None and entry["data_bytes"] == exp + off)
    else:
        entry["data_bytes"] = None
        entry["size_matches"] = None
    return entry


def find_data_file(hdr_path):
    """由 .hdr 路径找同名数据文件：依次试 .dat/.img/.raw/.bin/.tif/无扩展名。"""
    root, ext = os.path.splitext(hdr_path)
    if ext.lower() != ".hdr":
        root = hdr_path
    for cand_ext in DATA_EXTS:
        cand = root + cand_ext
        if os.path.isfile(cand) and cand != hdr_path:
            return cand
    return None


def find_hdr_file(data_path):
    root, _ext = os.path.splitext(data_path)
    for cand in (data_path + ".hdr", root + ".hdr"):
        if os.path.isfile(cand):
            return cand
    return None
# ==== HDR-SHARED-END ========================================================


# ---------------------------------------------------------------- preflight
def cmd_preflight(args):
    report = {"ok": True, "action": "preflight", "python": sys.version.split()[0],
              "checks": {}, "envi_available": False}
    # 1) hdr 解析能力（纯 Python，永远可用）
    report["checks"]["hdr_parser"] = "ok (pure python, no ENVI needed)"
    # 2) idlpy
    try:
        import idlpy
        report["checks"]["idlpy_import"] = "ok"
        report["idlpy_file"] = getattr(idlpy, "__file__", "unknown")
        report["envi_available"] = True
    except Exception as e:
        report["checks"]["idlpy_import"] = "fail: %s" % e
        report["envi_available"] = False
    # 3) 安装线索：环境变量与常见目录（仅报告，不作断言）
    hints = {}
    for var in ("IDL_DIR", "EXELIS_DIR", "HARRIS_DIR", "NV5_DIR"):
        if os.environ.get(var):
            hints[var] = os.environ[var]
    for cand in (r"C:\Program Files\Harris", r"C:\Program Files\NV5",
                 r"C:\Program Files\Exelis", r"C:\Program Files\L3Harris",
                 "/usr/local/harris", "/usr/local/nv5", "/usr/local/exelis",
                 "/opt/harris", "/opt/nv5"):
        if os.path.isdir(cand):
            hints.setdefault("install_dirs", []).append(cand)
    for exe in ("idl", "envi"):
        found = shutil.which(exe)
        if found:
            hints.setdefault("on_path", []).append(found)
    report["install_hints"] = hints
    if not report["envi_available"]:
        return fail("IDLPY_NOT_AVAILABLE",
                    "idlpy 导入失败：本机未发现可用的 IDL/ENVI Python 桥。"
                    "注意 inventory/backup 只靠 .hdr 解析与文件复制，不受影响。",
                    report=report)
    return emit(report)


# ---------------------------------------------------------------- inventory
def cmd_inventory(args):
    target = args.target
    notes = []
    hdr_files = []
    if os.path.isdir(target):
        for name in sorted(os.listdir(target)):
            if name.lower().endswith(".hdr"):
                hdr_files.append(os.path.join(target, name))
        if not hdr_files:
            return fail("NO_HDR_FOUND", "目录内没有 .hdr 文件: %s" % target)
    elif os.path.isfile(target):
        if target.lower().endswith(".hdr"):
            hdr_files = [target]
        else:
            hdr = find_hdr_file(target)
            if hdr is None:
                return fail("HDR_NOT_FOUND", "栅格数据文件旁没有同名 .hdr: %s" % target)
            hdr_files = [hdr]
    else:
        return fail("FILE_NOT_FOUND", "目标不存在: %s" % target)
    rasters = []
    for hdr in hdr_files:
        try:
            rasters.append(hdr_summary(hdr))
        except Exception as e:
            rasters.append({"hdr": hdr, "ok": False,
                            "error_code": "HDR_PARSE_FAILED", "message": str(e)})
    ok_count = sum(1 for r in rasters if r.get("ok") is not False)
    return emit({"ok": True, "action": "inventory", "target": target,
                 "source": "hdr-parse", "count": len(rasters),
                 "parsed": ok_count, "rasters": rasters, "notes": notes})


# ------------------------------------------------------------------- backup
def cmd_backup(args):
    src = args.raster
    if not os.path.exists(src):
        return fail("FILE_NOT_FOUND", "栅格路径不存在: %s" % src)
    if src.lower().endswith(".hdr"):
        hdr = src
        data = find_data_file(src)
    else:
        data = src
        hdr = find_hdr_file(src)
    if hdr is None or not os.path.isfile(hdr):
        return fail("HDR_NOT_FOUND", "找不到配套 .hdr，拒绝备份不完整栅格对: %s" % src)
    if data is None or not os.path.isfile(data):
        return fail("DATA_FILE_NOT_FOUND", ".hdr 旁找不到数据文件: %s" % hdr)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    copied = []
    for path in (data, hdr):
        root, ext = os.path.splitext(path)
        dst = "%s.bak-%s%s" % (root, stamp, ext)
        if os.path.exists(dst):
            return fail("BACKUP_EXISTS", "目标备份已存在，拒绝覆盖: %s" % dst)
        shutil.copy2(path, dst)
        copied.append({"source": path, "backup": dst,
                       "bytes": os.path.getsize(dst), "sha256": sha256_of(dst)})
    return emit({"ok": True, "action": "backup", "files": copied})


def main():
    _wrap_stdout()
    p = argparse.ArgumentParser(prog="envi_bridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preflight")
    pp.set_defaults(func=cmd_preflight)
    ip = sub.add_parser("inventory")
    ip.add_argument("target", help=".hdr 文件 / 栅格数据文件 / 目录")
    ip.set_defaults(func=cmd_inventory)
    bp = sub.add_parser("backup")
    bp.add_argument("raster", help="栅格数据文件或其 .hdr")
    bp.set_defaults(func=cmd_backup)
    args = p.parse_args()
    _pg_err = _path_guard(args)
    if _pg_err:
        return fail("PATH_GUARD_REJECTED", _pg_err, error="PATH_GUARD_REJECTED")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
