# -*- coding: utf-8 -*-
"""
probe_mapgis.py — MapGIS Python 环境探测探针（只读，本包核心交付）

背景：MapGIS（中地数码）官方称 MapGIS Objects SDK 提供 C++/Java/Python 开发
资源，但 Python 绑定的模块名、安装位置、可用入口均无公开权威文档，本探针
的职责就是在目标机器上把这件事查清楚。探针输出的 JSON 是下一步立项
（走哪条桥接路线）的唯一依据；在探针给出肯定结论之前，本包不声称任何
MapGIS API 可用。

探测策略：
  1) 环境变量线索：MAPGIS_HOME / ZONDY_HOME / MAPGIS_PATH / ZONDY_PATH
  2) 安装目录启发式：扫描 Program Files 等根目录下名称含 mapgis / zondy 的目录
  3) 候选模块名逐个 import 试探（见 CANDIDATE_MODULES），逐个记录成败与报错
  4) 任一模块导入成功：枚举其顶层符号与类成员方法清单（截断上限见代码），
     供维护者判断真实 API 形态

输出：单行 JSON 到 stdout。找到可用模块 exit 0；全部失败输出结构化
MAPGIS_PYTHON_NOT_FOUND 加完整尝试清单，exit 1。
本探针只读：不写文件、不改环境、不安装任何东西。
"""
import importlib
import io
import json
import os
import platform
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# 候选模块名：来自厂商命名习惯（Zondy 为中地数码英文名）与常见 Python 绑定
# 命名风格的启发式清单。清单本身不构成"这些模块存在"的断言——逐个试过才算数。
CANDIDATE_MODULES = [
    "mapgis",
    "MapGIS",
    "mapgis_objects",
    "mapgisobjects",
    "MapGISObjects",
    "mapgis_python",
    "zondy",
    "Zondy",
    "zondygis",
    "ZondyGIS",
    "zondy_objects",
    "zgis",
]

ENV_HINT_VARS = ["MAPGIS_HOME", "ZONDY_HOME", "MAPGIS_PATH", "ZONDY_PATH"]
MAX_SYMBOLS = 200
MAX_METHODS = 200


def find_install_dirs():
    """启发式扫描常见安装根目录，返回名称含 mapgis/zondy 的目录列表。"""
    roots = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        val = os.environ.get(var)
        if val:
            roots.append(val)
    roots.extend(["C:\\", "D:\\", "E:\\"])
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            entries = os.listdir(root)
        except Exception:
            continue
        for name in entries:
            low = name.lower()
            if "mapgis" in low or "zondy" in low:
                path = os.path.join(root, name)
                if os.path.isdir(path):
                    found.append(path)
    return sorted(set(found))


def describe_module(mod):
    """枚举已导入模块的顶层符号与类的公开方法清单（带截断上限）。"""
    info = {
        "module": mod.__name__,
        "file": getattr(mod, "__file__", None),
        "version": str(getattr(mod, "__version__", "unknown")),
    }
    tops = [n for n in dir(mod) if not n.startswith("_")]
    info["top_symbols"] = tops[:MAX_SYMBOLS]
    info["top_symbol_count"] = len(tops)
    classes = {}
    for name in tops:
        try:
            obj = getattr(mod, name)
        except Exception:
            continue
        if isinstance(obj, type):
            methods = [m for m in dir(obj) if not m.startswith("_")]
            classes[name] = methods[:MAX_METHODS]
    info["classes"] = classes
    return info


def load_found_module():
    """按候选顺序重新导入第一个可导入的模块，返回 module 对象或 None。

    供同包其他脚本（如 inspect 的多策略尝试）拿到真实模块对象用；
    每次调用都会重新走一遍 import 试探，失败细节请看 run_probe 的清单。
    """
    for name in CANDIDATE_MODULES:
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def run_probe():
    result = {
        "ok": False,
        "action": "probe",
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": platform.platform(),
        "env_hints": {v: os.environ.get(v) for v in ENV_HINT_VARS
                      if os.environ.get(v)},
        "install_dirs_found": find_install_dirs(),
        "module_attempts": [],
        "found": None,
    }
    for name in CANDIDATE_MODULES:
        attempt = {"module": name, "ok": False, "error": None}
        try:
            mod = importlib.import_module(name)
        except Exception as e:
            attempt["error"] = "%s: %s" % (type(e).__name__, e)
            result["module_attempts"].append(attempt)
            continue
        attempt["ok"] = True
        result["module_attempts"].append(attempt)
        result["found"] = describe_module(mod)
        result["ok"] = True
        break
    if not result["ok"]:
        result["error_code"] = "MAPGIS_PYTHON_NOT_FOUND"
        result["message"] = (
            "全部候选模块名均导入失败，且未证实存在可用的 MapGIS Python 绑定；"
            "install_dirs_found 与 module_attempts 为完整尝试清单。"
            "在实机探针给出肯定结论之前，不许据此声称 MapGIS Python API 可用。")
    return result


def main():
    result = run_probe()
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
