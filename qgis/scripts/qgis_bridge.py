# -*- coding: utf-8 -*-
"""
qgis_bridge.py — QGIS 工程文件桥接脚本（v0.2，只读优先）

子命令：
  preflight  环境预检（探测 qgis python 模块、qgis / qgis_process 命令；
             纯文件解析模式不需要 QGIS 也可用，会如实回报）
  backup     备份工程文件（时间戳副本 + sha256），纯标准库
  inspect    工程盘点，双策略：
               策略一 headless-file-parse —— 纯 Python 标准库解析 .qgs XML /
                       .qgz（zip 内的 .qgs），不装 QGIS 也能盘点；
               策略二 headless-qgis —— 用 QgsApplication 无头打开工程后枚举。
             两种策略都会先把工程复制到临时目录再打开（原件零接触），
             实际命中的策略记入输出的 mode / opened_via 字段。

设计约束：
  - 一切结果以单行 JSON 输出到 stdout；失败也是 JSON，退出码非 0。
  - 本脚本不包含任何写业务动作（不 save、不删、不改）。
  - qgis 模块一律惰性导入：没有 QGIS 的机器上 parse 策略照常工作。
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
import zipfile
import xml.etree.ElementTree as ET
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


# ---------------------------------------------------------------- preflight
def _which_all(names):
    found = {}
    for n in names:
        p = shutil.which(n)
        if p:
            found[n] = p
    return found


def _qgis_import_probe():
    """惰性探测 qgis 模块；返回 (info_dict, ok)。"""
    info = {}
    try:
        import qgis
        info["module_file"] = getattr(qgis, "__file__", "unknown")
    except Exception as e:
        info["error"] = "import qgis failed: %s" % e
        return info, False
    try:
        from qgis.core import Qgis
        info["version"] = getattr(Qgis, "QGIS_VERSION", "unknown")
        info["release"] = getattr(Qgis, "QGIS_RELEASE_NAME", "unknown")
    except Exception as e:
        info["core_error"] = "import qgis.core.Qgis failed: %s" % e
        return info, False
    return info, True


def _common_install_hints():
    hints = []
    for p in ("/usr/bin/qgis", "/usr/bin/qgis_process",
              "/Applications/QGIS.app/Contents/MacOS/QGIS"):
        if os.path.exists(p):
            hints.append(p)
    prefix = os.environ.get("QGIS_PREFIX_PATH")
    if prefix:
        hints.append("QGIS_PREFIX_PATH=%s" % prefix)
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    try:
        for name in sorted(os.listdir(pf)):
            if name.upper().startswith("QGIS"):
                hints.append(os.path.join(pf, name))
    except Exception:
        pass
    return hints


def cmd_preflight(args):
    report = {"ok": True, "action": "preflight",
              "python": sys.version.split()[0], "checks": {}}
    info, ok = _qgis_import_probe()
    report["checks"]["qgis_import"] = "ok" if ok else "fail"
    report["qgis"] = info
    cmds = _which_all(["qgis", "qgis_process"])
    report["checks"]["commands"] = cmds
    report["install_hints"] = _common_install_hints()
    modes = ["headless-file-parse"]
    if ok:
        modes.append("headless-qgis")
        modes.append("live (in QGIS Python console)")
    report["ready_modes"] = modes
    report["note"] = ("headless-file-parse 仅用 Python 标准库解析 .qgs/.qgz，"
                      "不依赖 QGIS 安装；其余模式需要可导入的 qgis 模块。")
    return emit(report)


# ------------------------------------------------------------------- backup
# 工程同名数据线索：backup 只复制工程文件本身，下列同名文件/目录仅作提示回报，
# 提醒使用者工程可能引用了相对路径数据，迁移备份时需一并处理。
_SIDECAR_EXTS = (".shp", ".shx", ".dbf", ".prj", ".qpj", ".gpkg", ".sqlite",
                 ".tif", ".tiff", ".vrt", ".geojson", ".csv")


def cmd_backup(args):
    src = args.project
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工程文件不存在: %s" % src)
    if os.path.splitext(src)[1].lower() not in (".qgs", ".qgz"):
        return fail("UNSUPPORTED_FORMAT", "仅支持 .qgs / .qgz 工程文件: %s" % src)
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
    base = os.path.basename(root)
    parent = os.path.dirname(os.path.abspath(src))
    sibling_dir = os.path.join(parent, base)
    sidecars = []
    try:
        for name in sorted(os.listdir(parent)):
            low = name.lower()
            if name == os.path.basename(src):
                continue
            if low.startswith(base.lower()) and low.endswith(_SIDECAR_EXTS):
                sidecars.append(name)
    except Exception:
        pass
    return emit({"ok": True, "action": "backup", "source": src, "backup": dst,
                 "bytes": os.path.getsize(dst), "sha256": h.hexdigest(),
                 "same_name_dir": sibling_dir if os.path.isdir(sibling_dir) else None,
                 "sidecar_data_candidates": sidecars,
                 "note": "仅备份了工程文件本身；same_name_dir / sidecar_data_candidates "
                         "是同名数据线索（未复制），工程若用相对路径引用它们，"
                         "迁移备份时需自行一并带走。"})


# ------------------------------------------------------------- XML 解析盘点
def _read_project_xml(path, notes):
    """从 .qgs 或 .qgz 读出工程 XML 根元素。返回 (root_element, inner_name)。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".qgs":
        with open(path, "rb") as f:
            data = f.read()
        return ET.fromstring(data), os.path.basename(path)
    if ext == ".qgz":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".qgs")]
            if not names:
                raise ValueError(".qgz 内未找到 .qgs 成员: %s" % z.namelist())
            if len(names) > 1:
                notes.append(".qgz 内有多个 .qgs，取第一个: %s" % names[0])
            return ET.fromstring(z.read(names[0])), names[0]
    raise ValueError("不支持的工程格式: %s" % ext)


def _text(elem, tag):
    child = elem.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _layer_crs_authid(maplayer):
    for sub in maplayer.iter():
        if sub.tag in ("srs", "crs"):
            auth = sub.find(".//authid")
            if auth is not None and auth.text:
                return auth.text.strip()
    return None


def _parse_layers(root):
    layers = []
    for ml in root.iter("maplayer"):
        provider_el = ml.find("provider")
        layers.append({
            "id": _text(ml, "id"),
            "name": _text(ml, "layername"),
            "type": ml.get("type"),
            "datasource": _text(ml, "datasource"),
            "provider": (provider_el.text.strip()
                         if provider_el is not None and provider_el.text else None),
            "crs_authid": _layer_crs_authid(ml),
            "embedded": ml.get("embedded") == "1",
        })
    return layers


def _parse_layer_tree(root):
    """递归走 layer-tree-group，输出带 group 路径的有序图层清单。"""
    out = []

    def walk(group, path):
        for child in group:
            if child.tag == "layer-tree-layer":
                checked = child.get("checked", "")
                out.append({
                    "id": child.get("id"),
                    "name": child.get("name"),
                    "checked": checked,
                    "visible": checked.endswith("Checked") and "Un" not in checked,
                    "group": "/".join(path) if path else None,
                })
            elif child.tag == "layer-tree-group":
                walk(child, path + [child.get("name") or ""])

    for grp in root.iter("layer-tree-group"):
        # 只从最外层 group 开始（iter 会同时给出嵌套 group，靠父级判断跳过）
        walk(grp, [])
        break
    return out


def _parse_project_xml(path, notes):
    root, inner = _read_project_xml(path, notes)
    canvas_crs = None
    dest = root.find(".//destinationsrs")
    if dest is not None:
        auth = dest.find(".//authid")
        if auth is not None and auth.text:
            canvas_crs = auth.text.strip()
    layouts = [el.get("name") for el in root.iter("Layout") if el.get("name")]
    title = _text(root, "title") or root.get("projectname")
    return {
        "format_inner": inner,
        "qgis_version_attr": root.get("version"),
        "title": title,
        "canvas_crs_authid": canvas_crs,
        "layers": _parse_layers(root),
        "layer_tree": _parse_layer_tree(root),
        "layouts": layouts,
    }


def _inspect_parse(path, work_copy, notes):
    parsed = _parse_project_xml(work_copy, notes)
    parsed["layer_count"] = len(parsed["layers"])
    return parsed


# ------------------------------------------------------- QgsApplication 盘点
def _inspect_qgis(path, work_copy, notes):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication, QgsProject
    prefix_candidates = []
    env_prefix = os.environ.get("QGIS_PREFIX_PATH")
    if env_prefix:
        prefix_candidates.append(env_prefix)
    try:
        import qgis.core as _qc
        prefix_candidates.append(os.path.abspath(
            os.path.join(os.path.dirname(_qc.__file__), "..", "..")))
    except Exception:
        pass
    prefix_candidates.append("/usr")
    app = QgsApplication([], False)
    inited = False
    used_prefix = None
    for prefix in prefix_candidates:
        try:
            QgsApplication.setPrefixPath(prefix, True)
            app.initQgis()
            inited = True
            used_prefix = prefix
            break
        except Exception as e:
            notes.append("initQgis(prefix=%s) failed: %s" % (prefix, e))
    if not inited:
        raise RuntimeError("QgsApplication.initQgis 全部前缀策略失败: %s" % notes)
    try:
        project = QgsProject.instance()
        if not project.read(work_copy):
            raise RuntimeError("QgsProject.read 返回 False: %s" % work_copy)
        layers = []
        for layer in project.mapLayers().values():
            entry = {"id": layer.id(), "name": layer.name(),
                     "type": str(layer.type()), "datasource": layer.source(),
                     "provider": layer.providerType(),
                     "valid": layer.isValid()}
            try:
                entry["crs_authid"] = layer.crs().authid()
            except Exception:
                entry["crs_authid"] = None
            layers.append(entry)
        crs = None
        try:
            crs = project.crs().authid()
        except Exception:
            pass
        layouts = []
        try:
            layouts = [lay.name() for lay in project.layoutManager().layouts()]
        except Exception as e:
            notes.append("layoutManager failed: %s" % e)
        return {"qgs_prefix_used": used_prefix,
                "title": project.title() or None,
                "file_name": project.fileName() or None,
                "project_crs_authid": crs,
                "layers": layers, "layer_count": len(layers),
                "layouts": layouts}
    finally:
        try:
            app.exitQgis()
        except Exception:
            pass


def cmd_inspect(args):
    src = args.project
    if not os.path.isfile(src):
        return fail("FILE_NOT_FOUND", "工程文件不存在: %s" % src)
    if os.path.splitext(src)[1].lower() not in (".qgs", ".qgz"):
        return fail("UNSUPPORTED_FORMAT", "仅支持 .qgs / .qgz 工程文件: %s" % src)
    notes = []
    tmpdir = tempfile.mkdtemp(prefix="qgisbridge-")
    work_copy = os.path.join(tmpdir, os.path.basename(src))
    shutil.copy2(src, work_copy)
    try:
        strategy = args.strategy
        qgis_ok = False
        if strategy in ("auto", "qgis"):
            _info, qgis_ok = _qgis_import_probe()
        if strategy == "qgis" and not qgis_ok:
            return fail("QGIS_NOT_AVAILABLE",
                        "--strategy qgis 但 qgis 模块不可导入", notes=notes)
        if strategy == "parse" or (strategy == "auto" and not qgis_ok):
            result = _inspect_parse(src, work_copy, notes)
            mode, via = "headless-file-parse", "xml.etree(.qgs/.qgz member)"
        else:
            result = _inspect_qgis(src, work_copy, notes)
            mode, via = "headless-qgis", "QgsApplication+QgsProject.read"
        out = {"ok": True, "action": "inspect", "source": src,
               "mode": mode, "opened_via": via, "notes": notes}
        out.update(result)
        return emit(out)
    except Exception as e:
        return fail("INSPECT_FAILED", "盘点失败: %s" % e, notes=notes,
                    traceback_tail=traceback.format_exc()[-500:])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(prog="qgis_bridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("preflight")
    pp.set_defaults(func=cmd_preflight)
    bp = sub.add_parser("backup")
    bp.add_argument("project")
    bp.set_defaults(func=cmd_backup)
    ip = sub.add_parser("inspect")
    ip.add_argument("project")
    ip.add_argument("--strategy", choices=("auto", "parse", "qgis"), default="auto",
                    help="auto=qgis 可导入时用策略二，否则策略一（默认）")
    ip.set_defaults(func=cmd_inspect)
    args = p.parse_args()
    _pg_err = _path_guard(args)
    if _pg_err:
        return fail("PATH_GUARD_REJECTED", _pg_err, error="PATH_GUARD_REJECTED")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
