# -*- coding: utf-8 -*-
"""
supermap_bridge.py — SuperMap 工程文件桥接脚本（v0.1，只读优先）

子命令：
  preflight  环境与许可预检（导入 iobjectspy、配置 iObjects Java 路径、许可冒烟）
  backup     备份工作空间文件（时间戳副本 + sha256），纯标准库
  inspect    工程盘点：复制到临时目录后打开，枚举数据源/数据集/地图，输出 JSON

设计约束：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - inspect 永不直接打开原件；先复制到临时目录。
  - 对 iobjectspy 的枚举接口采用多策略自适应（不同小版本 API 命名有差异），
    实际命中的策略记入输出的 api_path 字段，供维护者据实收紧。
  - 本脚本不包含任何写业务动作（不 save、不删、不改）。
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
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


# ---------------------------------------------------------------- preflight
def cmd_preflight(args):
    report = {"ok": True, "action": "preflight", "python": sys.version.split()[0],
              "checks": {}}
    # 1) import iobjectspy
    try:
        import iobjectspy
        report["checks"]["iobjectspy_import"] = "ok"
        report["iobjectspy_version"] = getattr(iobjectspy, "__version__", "unknown")
    except Exception as e:
        report["checks"]["iobjectspy_import"] = "fail"
        return fail("IOBJECTSPY_NOT_INSTALLED",
                    "iobjectspy 导入失败: %s" % e, report=report)
    # 2) iObjects Java path
    if args.iobjects_java:
        try:
            iobjectspy.set_iobjects_java_path(args.iobjects_java)
            report["checks"]["set_iobjects_java_path"] = "ok(%s)" % args.iobjects_java
        except Exception as e:
            report["checks"]["set_iobjects_java_path"] = "fail: %s" % e
    else:
        report["checks"]["set_iobjects_java_path"] = "skipped (relying on existing config)"
    # 3) license smoke test: constructing a Workspace triggers license validation
    try:
        from iobjectspy import Workspace
        ws = Workspace()
        try:
            ws.close()
        except Exception:
            pass
        report["checks"]["license_smoke"] = "ok"
    except Exception as e:
        msg = str(e)
        code = "LICENSE_UNAVAILABLE" if "hasp" in msg.lower() else "WORKSPACE_INIT_FAILED"
        report["checks"]["license_smoke"] = "fail"
        return fail(code, "许可/工作空间初始化失败: %s" % msg, report=report)
    return emit(report)


# ------------------------------------------------------------------- backup
def cmd_backup(args):
    src = args.workspace
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工作空间文件不存在: %s" % src)
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


# ------------------------------------------------------------------ helpers
# ==== ENUM-SHARED-BEGIN =====================================================
# 数据源/数据集枚举的共享实现，与本包另一侧桥（无头桥 scripts/supermap_bridge.py
# / 实时桥 live/inapp_bridge.py）中的同名块保持逐字一致：两侧运行形态不同
# （一个是命令行脚本、一个必须单文件在 iDesktopX Python 窗口 exec），无法互相
# import，只能以内联副本同步维护。修改任一侧后必须同步另一侧。
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


def _get_item(coll, i):
    """集合下标访问兜底：coll[i] / coll.get(i) / coll.get_item(i) / coll.item(i)。"""
    try:
        return coll[i]
    except Exception:
        pass
    for name in ("get", "get_item", "item"):
        fn = getattr(coll, name, None)
        if callable(fn):
            try:
                return fn(i)
            except Exception:
                continue
    return None


def _to_list(coll):
    """把集合尽量转成 list：可迭代优先，其次 count+下标兜底。"""
    if coll is None:
        return []
    try:
        return list(coll)
    except Exception:
        pass
    count, _ = _try_attrs(coll, ["get_count", "count"])
    if not isinstance(count, int):
        try:
            count = len(coll)
        except Exception:
            count = None
    if isinstance(count, int):
        return [_get_item(coll, i) for i in range(count)]
    return []


def _safe_str(v):
    try:
        return str(v)
    except Exception:
        return None


def _ds_summary(ds):
    alias, _ = _try_attrs(ds, ["get_alias", "alias", "get_name", "name"])
    engine, _ = _try_attrs(ds, ["get_engine_type", "engine_type"])
    if engine is None:
        # iobjectspy 10.1.0 实机验证：引擎类型挂在 connection_info.type 上
        conn, _ = _try_attrs(ds, ["get_connection_info", "connection_info"])
        if conn is not None:
            engine, _ = _try_attrs(conn, ["get_type", "type"])
    return {"alias": _safe_str(alias),
            "engine": _safe_str(getattr(engine, "name", engine))}


def _dataset_entry(d):
    name, _ = _try_attrs(d, ["get_name", "name"])
    dtype, _ = _try_attrs(d, ["get_type", "type"])
    return {"name": _safe_str(name), "type": _safe_str(dtype)}
# ==== ENUM-SHARED-END =======================================================


# ------------------------------------------------------------------ inspect
def _open_workspace(iobjectspy, path, notes):
    """多策略打开工作空间，返回 (workspace, strategy_name)。"""
    # 策略 0（iDesktop 10i + iobjectspy 10.1.0 实机验证）：WorkspaceConnectionInfo 传入路径，
    # 且 Workspace.open() 返回的是"新"的工作空间对象——必须接住返回值，旧句柄会已释放。
    try:
        from iobjectspy import Workspace, WorkspaceConnectionInfo
        ws0 = Workspace()
        opened = ws0.open(WorkspaceConnectionInfo(path))
        if opened is not None:
            return opened, "Workspace.open(WorkspaceConnectionInfo)->returned"
        try:
            ws0.close()
        except Exception:
            pass
        notes.append("WorkspaceConnectionInfo 策略返回空对象")
    except Exception as e:
        notes.append("WorkspaceConnectionInfo strategy failed: %s" % e)
    # 策略 1：模块级 helper open_workspace
    helper = getattr(iobjectspy, "open_workspace", None)
    if callable(helper):
        try:
            ws = helper(path)
            if ws is not None:
                return ws, "iobjectspy.open_workspace"
        except Exception as e:
            notes.append("open_workspace helper failed: %s" % e)
    # 策略 2：Workspace().open(path)
    from iobjectspy import Workspace
    ws = Workspace()
    try:
        ws.open(path)
        return ws, "Workspace.open"
    except Exception as e:
        notes.append("Workspace.open failed: %s" % e)
    # 策略 3：Workspace 连接信息对象
    try:
        from iobjectspy import WorkspaceConnectionInfo
        info = WorkspaceConnectionInfo()
        try:
            info.set_server(path)
        except Exception:
            info.server = path
        ws.open(info)
        return ws, "Workspace.open(WorkspaceConnectionInfo)"
    except Exception as e:
        notes.append("WorkspaceConnectionInfo strategy failed: %s" % e)
    try:
        ws.close()
    except Exception:
        pass
    return None, None


def _inspect_datasource(ds, notes):
    info = _ds_summary(ds)
    conn, _ = _try_attrs(ds, ["get_connection_info", "connection_info"])
    server, _ = _try_attrs(conn, ["get_server", "server"]) if conn is not None else (None, None)
    info["server"] = _safe_str(server)
    datasets = []
    coll, via = _try_attrs(ds, ["get_datasets", "datasets"])
    if coll is None:
        first, _ = _try_attrs(ds, ["first_dataset"])
        items = [first] if first is not None else []
        via = "first_dataset" if first is not None else None
    else:
        items = _to_list(coll)
    info["datasets_via"] = via
    for d in items:
        if d is None:
            continue
        entry = _dataset_entry(d)
        cnt, _ = _try_attrs(d, ["get_record_count", "record_count"])
        entry["record_count"] = cnt if isinstance(cnt, int) else None
        prj, _ = _try_attrs(d, ["get_prj_coord_sys", "prj_coord_sys"])
        entry["prj"] = _safe_str(prj.get_name()) if prj is not None and hasattr(prj, "get_name") else _safe_str(prj)
        datasets.append(entry)
    info["datasets"] = datasets
    return info


def _copy_sidecar_datasources(src, tmpdir, notes):
    """把工作空间同目录（及其一级子目录）里的数据源文件复制进临时目录。

    iDesktop 工作空间里的数据源连接常是相对路径（如 jidi.udbx），只复制 .smwu
    会让数据源指向不存在的临时路径，盘点时表现为"数据集为空"的假象。
    只复制数据文件，不碰文档/图片等其它内容。
    """
    exts = (".udb", ".udbx", ".udd")
    src_dir = os.path.dirname(os.path.abspath(src))
    copied = []

    def _walk(base, depth):
        if depth > 1:
            return
        try:
            entries = os.listdir(base)
        except Exception:
            return
        for name in entries:
            full = os.path.join(base, name)
            if os.path.abspath(full) == os.path.abspath(src):
                continue
            if os.path.isdir(full):
                _walk(full, depth + 1)
                continue
            if not name.lower().endswith(exts):
                continue
            rel = os.path.relpath(full, src_dir)
            dst = os.path.join(tmpdir, rel)
            try:
                parent = os.path.dirname(dst)
                if parent and not os.path.isdir(parent):
                    os.makedirs(parent)
                shutil.copy2(full, dst)
                copied.append(rel.replace("\\", "/"))
            except Exception as e:
                notes.append("复制数据源 %s 失败: %s" % (rel, e))

    _walk(src_dir, 0)
    if copied:
        notes.append("为解析相对路径，已一并复制同级数据源: %s" % ", ".join(copied))
    return copied


def cmd_inspect(args):
    src = args.workspace
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工作空间文件不存在: %s" % src)
    try:
        import iobjectspy
    except Exception as e:
        return fail("IOBJECTSPY_NOT_INSTALLED", "iobjectspy 导入失败: %s" % e)
    if args.iobjects_java:
        try:
            iobjectspy.set_iobjects_java_path(args.iobjects_java)
        except Exception:
            pass
    notes = []
    tmpdir = tempfile.mkdtemp(prefix="smbridge-")
    work_copy = os.path.join(tmpdir, os.path.basename(src))
    shutil.copy2(src, work_copy)
    _copy_sidecar_datasources(src, tmpdir, notes)
    ws = None
    try:
        ws, strategy = _open_workspace(iobjectspy, work_copy, notes)
        if ws is None:
            return fail("OPEN_WORKSPACE_FAILED", "全部打开策略均失败", notes=notes,
                        traceback_tail=traceback.format_exc()[-500:])
        result = {"ok": True, "action": "inspect", "source": src,
                  "opened_via": strategy, "api_path": {}, "notes": notes}
        # --- datasources
        coll, via = _try_attrs(ws, ["get_datasources", "datasources"])
        result["api_path"]["datasources"] = via
        ds_list = []
        for ds in _to_list(coll):
            if ds is not None:
                ds_list.append(_inspect_datasource(ds, notes))
        result["datasources"] = ds_list
        # --- maps (names only in v0.1; layer detail depends on probe results)
        maps_coll, via = _try_attrs(ws, ["get_maps", "maps"])
        result["api_path"]["maps"] = via
        map_names = []
        for m in _to_list(maps_coll):
            nm, _ = _try_attrs(m, ["get_name", "name"])
            map_names.append(_safe_str(nm if nm is not None else m))
        result["maps"] = map_names
        result["notes"] = notes
        return emit(result)
    except Exception as e:
        return fail("INSPECT_FAILED", "盘点失败: %s" % e, notes=notes,
                    traceback_tail=traceback.format_exc()[-500:])
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(prog="supermap_bridge")
    # Python 3.5 的 argparse 不支持 add_subparsers(required=True)，改为手动校验
    sub = p.add_subparsers(dest="cmd")
    pp = sub.add_parser("preflight")
    pp.add_argument("--iobjects-java", default=None)
    pp.set_defaults(func=cmd_preflight)
    bp = sub.add_parser("backup")
    bp.add_argument("workspace")
    bp.set_defaults(func=cmd_backup)
    ip = sub.add_parser("inspect")
    ip.add_argument("workspace")
    ip.add_argument("--iobjects-java", default=None)
    ip.set_defaults(func=cmd_inspect)
    args = p.parse_args()
    func = getattr(args, "func", None)
    if func is None:
        p.print_help()
        return 2
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
