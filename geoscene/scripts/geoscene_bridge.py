# -*- coding: utf-8 -*-
"""
geoscene_bridge.py — GeoScene Pro 工程文件无头桥接脚本（v0.1，只读优先，
ArcGIS Pro 桥同源衍生版：GeoScene Pro 与 ArcGIS Pro 共用 arcpy 内核，
本脚本据此沿用同一套 arcpy.mp 操作；兼容性未经 GeoScene Pro 实机验证，
preflight 的 product_clue 字段用于确认当前 arcpy 到底属于哪个产品）

子命令：
  preflight  环境与许可预检（定位 ArcGIS Pro 自带 Python、导入 arcpy、读安装/许可信息）
  backup     备份工程文件（时间戳副本 + sha256），纯标准库；同名 .gdb 文件夹整体复制
  inspect    工程盘点：先把 .aprx 复制到临时目录再打开，枚举地图/图层/表/布局，输出 JSON

设计约束：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - inspect 永不直接打开原件；先复制到临时目录（同名 .gdb 一并复制，保证相对路径数据源可解析）。
  - 【关键事实】外部进程打开 .aprx 只能看到上次存盘的状态，看不到 GeoScene Pro
    界面里的未保存修改。inspect 输出固定标注 mode=headless-saved-state，不冒充实时。
  - 对 arcpy.mp 的访问采用防御式多策略（属性读取逐个兜底），命中的方式记入
    输出的 api_path / *_via 字段，供维护者据实收紧。
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


def _safe_str(v):
    if v is None:
        return None
    try:
        return str(v)
    except Exception:
        return None


def _try_attrs(obj, names):
    """按顺序尝试属性/方法，返回 (值, 命中的名字)；属性 getter 抛错也兜底；
    取到的方法会自动调用（无参）。arcpy 的某些属性（如图层 dataSource 对组图层）
    读取时会抛 RuntimeError，因此 getattr 本身也必须在 try 内。"""
    for name in names:
        if obj is None:
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        try:
            if callable(val):
                val = val()
            return val, name
        except Exception:
            continue
    return None, None


def _to_list(coll):
    if coll is None:
        return []
    try:
        return list(coll)
    except Exception:
        pass
    try:
        return [coll[i] for i in range(len(coll))]
    except Exception:
        return []


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- preflight
# GeoScene Pro 的典型安装线索（启发式，命中与否以 GetInstallInfo 原文为准）：
# 环境名候选依次为 geoscenepro-py3、arcgispro-py3（共用内核时可能沿用），
# 再兜底扫描安装目录下 bin\Python\envs\*\python.exe 的任意环境。
_ENV_PY_RELS = [os.path.join("bin", "Python", "envs", env_name, "python.exe")
                for env_name in ("geoscenepro-py3", "arcgispro-py3")]
_PROPY_REL = os.path.join("bin", "Python", "Scripts", "propy.bat")
_FIXED_INSTALL_DIRS = [r"C:\Program Files\GeoScene\Pro",
                       r"C:\Program Files (x86)\GeoScene\Pro",
                       r"C:\Program Files\GeoScene Pro",
                       r"C:\Program Files\GeoScene\GeoScenePro"]
_REGISTRY_KEYS = (r"SOFTWARE\GeoScene\GeoScenePro",
                  r"SOFTWARE\GeoScene\Pro",
                  r"SOFTWARE\ESRI\GeoScenePro")


def _find_geoscene_pythons():
    """多策略定位 GeoScene Pro 自带 Python / propy，返回 [{path, via}, ...]。
    注意：因共用 arcpy 内核，命中的也可能是机器上 Esri ArcGIS Pro 的解释器；
    候选只是线索，产品身份必须以 preflight 成功导入后的 GetInstallInfo 原文为准。"""
    found = []

    def _add(path, via):
        if path and os.path.isfile(path) and all(e["path"] != path for e in found):
            found.append({"path": path, "via": via})

    def _add_install_dir(install_dir, via):
        if not install_dir:
            return
        for rel in _ENV_PY_RELS:
            _add(os.path.join(install_dir, rel), via)
        _add(os.path.join(install_dir, _PROPY_REL), via + ":propy")
        # 兜底：扫描 envs 目录下任意环境的 python.exe
        try:
            envs_dir = os.path.join(install_dir, "bin", "Python", "envs")
            for name in sorted(os.listdir(envs_dir)):
                _add(os.path.join(envs_dir, name, "python.exe"), via + ":envs-scan")
        except Exception:
            pass

    # 策略 1：环境变量直指（GeoScene 优先，ArcGIS 的变量作共用内核回退线索）
    for var in ("GEOSCENE_PRO_PYTHON", "GEOSCENE_PYTHON",
                "ARCGIS_PRO_PYTHON", "ARCPY_PYTHON"):
        _add(os.environ.get(var), "env:%s" % var)
    # 策略 2：注册表 GeoScene 相关键的 InstallDir（仅 Windows）
    try:
        import winreg
        hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
        for hive in hives:
            for key in _REGISTRY_KEYS:
                subs = [key]
                parts = key.split(chr(92), 1)
                if len(parts) == 2:
                    subs.append(chr(92).join([parts[0], 'WOW6432Node', parts[1]]))
                for sub in subs:
                    try:
                        with winreg.OpenKey(hive, sub) as k:
                            install_dir, _ = winreg.QueryValueEx(k, "InstallDir")
                        _add_install_dir(install_dir, "registry:InstallDir")
                    except Exception:
                        continue
    except Exception:
        pass
    # 策略 3：固定安装路径
    for base in _FIXED_INSTALL_DIRS:
        _add_install_dir(base, "known-path")
    # 策略 4：PATH 上的 propy
    propy = shutil.which("propy")
    if propy:
        _add(propy, "PATH:propy")
    return found


def cmd_preflight(args):
    report = {"ok": True, "action": "preflight", "python": sys.version.split()[0],
              "interpreter": sys.executable, "checks": {}}
    try:
        import arcpy
        report["checks"]["arcpy_import"] = "ok"
        report["arcpy_file"] = getattr(arcpy, "__file__", "unknown")
    except Exception as e:
        report["checks"]["arcpy_import"] = "fail"
        return fail("ARCPY_NOT_AVAILABLE",
                    "当前解释器无法导入 arcpy: %s" % e,
                    report=report,
                    python_candidates=_find_geoscene_pythons(),
                    hint="请用 GeoScene Pro 自带 Python 或经 propy 重跑本脚本；"
                         "不要把 arcpy 装进无关的项目环境")
    # 安装信息（版本/许可级别）
    try:
        info = arcpy.GetInstallInfo()
        if isinstance(info, dict):
            report["install"] = {k: info.get(k) for k in
                                 ("ProductName", "Version", "InstallDir", "LicenseLevel")}
            # 产品身份线索：GeoScene 与 ArcGIS 共用 arcpy 内核，必须凭原文确认
            # 当前导入的 arcpy 到底属于哪个产品；looks_like 只是启发式标注。
            raw = "%s %s" % (info.get("ProductName"), info.get("InstallDir"))
            low = raw.lower()
            if "geoscene" in low:
                looks = "GeoScene"
            elif "arcgis" in low:
                looks = "ArcGIS"
            else:
                looks = "unknown"
            report["product_clue"] = {
                "product_name": info.get("ProductName"),
                "install_dir": info.get("InstallDir"),
                "looks_like": looks,
                "note": ("looks_like 为启发式判断，ProductName/InstallDir 原文为准；"
                         "若 looks_like 不是 GeoScene，说明当前解释器属于 Esri ArcGIS "
                         "而非 GeoScene，本桥的 GeoScene 兼容性结论不能据此成立，须如实回报。")}
        report["checks"]["install_info"] = "ok"
    except Exception as e:
        report["checks"]["install_info"] = "fail: %s" % e
    # 产品/许可状态
    try:
        report["product_info"] = _safe_str(arcpy.ProductInfo())
        report["checks"]["product_info"] = "ok"
    except Exception as e:
        report["checks"]["product_info"] = "fail: %s" % e
    # mp 子模块可用性
    try:
        from arcpy import mp
        report["checks"]["mp_module"] = "ok"
        report["mp_arcgisproject_available"] = hasattr(mp, "ArcGISProject")
    except Exception as e:
        report["checks"]["mp_module"] = "fail: %s" % e
    report["note"] = ("许可最终是否可用以 inspect 能否打开工程为准"
                      "（打开 .aprx 会触发许可检出）；本预检不打开任何工程文件。")
    return emit(report)


# ------------------------------------------------------------------- backup
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
    entries = [{"kind": "aprx", "source": src, "backup": dst,
                "bytes": os.path.getsize(dst), "sha256": _sha256_file(dst)}]
    # 同名 .gdb 文件夹（工程同级、与 .aprx 同名的文件地理数据库）整体复制
    gdb_src = root + ".gdb"
    if os.path.isdir(gdb_src):
        gdb_dst = "%s.bak-%s.gdb" % (root, stamp)
        if os.path.exists(gdb_dst):
            return fail("BACKUP_EXISTS", "目标 .gdb 备份已存在，拒绝覆盖: %s" % gdb_dst)
        shutil.copytree(gdb_src, gdb_dst)
        manifest = hashlib.sha256()
        file_count = 0
        total_bytes = 0
        for dirpath, _dirnames, filenames in os.walk(gdb_dst):
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, gdb_dst).replace(os.sep, "/")
                manifest.update(rel.encode("utf-8"))
                manifest.update(_sha256_file(full).encode("ascii"))
                file_count += 1
                total_bytes += os.path.getsize(full)
        entries.append({"kind": "gdb-folder", "source": gdb_src, "backup": gdb_dst,
                        "file_count": file_count, "total_bytes": total_bytes,
                        "manifest_sha256": manifest.hexdigest()})
    return emit({"ok": True, "action": "backup", "source": src,
                 "entries": entries,
                 "sha256": entries[0]["sha256"], "backup": dst})


# ------------------------------------------------------------------ inspect
def _layer_entry(layer):
    entry = {}
    name, _ = _try_attrs(layer, ["name"])
    entry["name"] = _safe_str(name)
    grp, _ = _try_attrs(layer, ["isGroupLayer"])
    entry["is_group_layer"] = grp if isinstance(grp, bool) else None
    vis, _ = _try_attrs(layer, ["visible"])
    entry["visible"] = vis if isinstance(vis, bool) else None
    broken, _ = _try_attrs(layer, ["isBroken"])
    entry["is_broken"] = broken if isinstance(broken, bool) else None
    labels, _ = _try_attrs(layer, ["showLabels"])
    entry["show_labels"] = labels if isinstance(labels, bool) else None
    # dataSource 对组图层/部分图层类型会抛错，且 supports() 本身也可能不可用，逐级兜底
    ds = None
    ds_via = None
    supports = getattr(layer, "supports", None)
    if callable(supports):
        try:
            if supports("DATASOURCE"):
                ds, ds_via = _try_attrs(layer, ["dataSource"])
        except Exception:
            ds, ds_via = None, None
    if ds is None and ds_via is None:
        ds, ds_via = _try_attrs(layer, ["dataSource"])
    entry["data_source"] = _safe_str(ds)
    entry["data_source_via"] = ds_via
    return entry


def _table_entry(table):
    entry = {}
    name, _ = _try_attrs(table, ["name"])
    entry["name"] = _safe_str(name)
    ds, ds_via = _try_attrs(table, ["dataSource"])
    entry["data_source"] = _safe_str(ds)
    entry["data_source_via"] = ds_via
    broken, _ = _try_attrs(table, ["isBroken"])
    entry["is_broken"] = broken if isinstance(broken, bool) else None
    return entry


def _open_project(mp, path, notes):
    """打开 .aprx（传入的是待打开路径：默认临时副本，--no-copy 时为原件）。
    返回 (aprx, via) 或 (None, None)。"""
    cls = getattr(mp, "ArcGISProject", None)
    if cls is None:
        notes.append("arcpy.mp 无 ArcGISProject 类")
        return None, None
    try:
        return cls(path), "arcpy.mp.ArcGISProject(path)"
    except Exception as e:
        notes.append("ArcGISProject(path) failed: %s" % e)
    return None, None


def cmd_inspect(args):
    src = args.project
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工程文件不存在: %s" % src)
    try:
        import arcpy  # noqa: F401  打开工程前先确认 arcpy 在场
        from arcpy import mp
    except Exception as e:
        return fail("ARCPY_NOT_AVAILABLE", "arcpy 导入失败: %s" % e,
                    python_candidates=_find_geoscene_pythons())
    notes = []
    # --no-copy：直接只读打开原件，拿真实数据源解析结果。默认仍是复制到临时目录，
    # 因为复制模式下 is_broken 会因「数据源没有随迁」而失真，只能反映
    # 「相对临时目录能否解析」，不足以判断真实断链。
    no_copy = bool(getattr(args, "no_copy", False))
    tmpdir = None
    sibling_gdb_copied = False
    if no_copy:
        work_copy = src
        copy_mode = "original"
        notes.append("no-copy: 直接只读打开原件，图层 is_broken 反映真实数据源状态；"
                     "本动作不写入、不移动原件")
    else:
        tmpdir = tempfile.mkdtemp(prefix="geobridge-")
        work_copy = os.path.join(tmpdir, os.path.basename(src))
        shutil.copy2(src, work_copy)
        copy_mode = "temp-copy"
        notes.append("temp-copy: 工程已复制到临时目录后打开，is_broken=true 可能仅因数据源"
                     "未随迁导致；要判断真实断链请加 --no-copy 复核")
        # 同名 .gdb 一并复制到临时目录：原件零接触的前提下让相对路径数据源可解析
        stem = os.path.splitext(os.path.basename(src))[0]
        gdb_src = os.path.join(os.path.dirname(os.path.abspath(src)), stem + ".gdb")
        if os.path.isdir(gdb_src):
            try:
                shutil.copytree(gdb_src, os.path.join(tmpdir, stem + ".gdb"))
                sibling_gdb_copied = True
            except Exception as e:
                notes.append("sibling .gdb copy failed: %s" % e)
    try:
        aprx, open_via = _open_project(mp, work_copy, notes)
        if aprx is None:
            return fail("OPEN_PROJECT_FAILED", "打开工程失败（许可不可用或工程损坏时也会在此失败）",
                        notes=notes, traceback_tail=traceback.format_exc()[-500:])
        result = {"ok": True, "action": "inspect", "source": src,
                  "mode": "headless-saved-state",
                  "copy_mode": copy_mode,
                  "mode_note": ("外部进程打开 .aprx 只能看到上次保存到磁盘的状态，"
                                "看不到 GeoScene Pro 界面里的未保存修改；"
                                "图层数据源为工程文件中记录的路径，本结果不代表界面实时状态。"),
                  "opened_via": open_via, "api_path": {},
                  "sibling_gdb_copied": sibling_gdb_copied, "notes": notes}
        fp, _ = _try_attrs(aprx, ["filePath"])
        result["project_file"] = _safe_str(fp)
        dgdb, _ = _try_attrs(aprx, ["defaultGeodatabase"])
        result["default_geodatabase"] = _safe_str(dgdb)
        # --- maps / layers / tables
        maps_coll, via = _try_attrs(aprx, ["listMaps"])
        result["api_path"]["maps"] = via
        maps_out = []
        for m in _to_list(maps_coll):
            if m is None:
                continue
            mname, _ = _try_attrs(m, ["name"])
            mtype, _ = _try_attrs(m, ["mapType"])
            m_entry = {"name": _safe_str(mname), "map_type": _safe_str(mtype)}
            layers_coll, lvia = _try_attrs(m, ["listLayers"])
            result["api_path"]["layers"] = lvia
            m_entry["layers"] = [_layer_entry(ly) for ly in _to_list(layers_coll)
                                 if ly is not None]
            tables_coll, tvia = _try_attrs(m, ["listTables"])
            result["api_path"]["tables"] = tvia
            m_entry["tables"] = [_table_entry(t) for t in _to_list(tables_coll)
                                  if t is not None]
            maps_out.append(m_entry)
        result["maps"] = maps_out
        # --- layouts
        layouts_coll, via = _try_attrs(aprx, ["listLayouts"])
        result["api_path"]["layouts"] = via
        layouts_out = []
        for lo in _to_list(layouts_coll):
            if lo is None:
                continue
            lname, _ = _try_attrs(lo, ["name"])
            pw, _ = _try_attrs(lo, ["pageWidth"])
            ph, _ = _try_attrs(lo, ["pageHeight"])
            lo_entry = {"name": _safe_str(lname),
                        "page_width": pw if isinstance(pw, (int, float)) else None,
                        "page_height": ph if isinstance(ph, (int, float)) else None}
            frames, fvia = _try_attrs(lo, ["listElements"])
            # listElements 需要参数，上面的无参调用一般会失败；直接带 MAPFRAME_ELEMENT 再试
            if frames is None:
                try:
                    frames = lo.listElements("MAPFRAME_ELEMENT")
                    fvia = "listElements(MAPFRAME_ELEMENT)"
                except Exception:
                    frames = None
            lo_entry["map_frames_via"] = fvia
            lo_entry["map_frame_count"] = len(_to_list(frames)) if frames is not None else None
            layouts_out.append(lo_entry)
        result["layouts"] = layouts_out
        result["notes"] = notes
        return emit(result)
    except Exception as e:
        return fail("INSPECT_FAILED", "盘点失败: %s" % e, notes=notes,
                    traceback_tail=traceback.format_exc()[-500:])
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(prog="geoscene_bridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preflight")
    pp.set_defaults(func=cmd_preflight)
    bp = sub.add_parser("backup")
    bp.add_argument("project")
    bp.set_defaults(func=cmd_backup)
    ip = sub.add_parser("inspect")
    ip.add_argument("project")
    ip.add_argument("--no-copy", action="store_true",
                    default=False,
                    help="直接只读打开原件（不复制到临时目录），用于拿真实 is_broken；")
    ip.set_defaults(func=cmd_inspect)
    args = p.parse_args()
    _pg_err = _path_guard(args)
    if _pg_err:
        return fail("PATH_GUARD_REJECTED", _pg_err, error="PATH_GUARD_REJECTED")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
