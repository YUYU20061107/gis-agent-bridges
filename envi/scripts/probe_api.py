# -*- coding: utf-8 -*-
"""
probe_api.py — ENVI / idlpy 校准探针（只读）
用途：首次部署或版本变更时运行一次，输出：
  1) idlpy 可用性与文件位置；
  2) .hdr 纯 Python 解析能力自检（不需要 ENVI）；
  3) 若 idlpy 可用：启动一个 HEADLESS ENVI 会话，回报 ENVI/IDL 版本，
     并抽样列出 ENVITask 任务名（多策略尝试，拿到什么报什么）。
输出为多行文本（非 JSON），请完整回传，不要删减。
注意：启动 ENVI 会话需要一份可用的 ENVI/IDL 许可；许可不可用时探针会
如实打印失败原因并退出，不许反复重试。
"""
import io
import os
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

SAMPLE_HDR = """ENVI
description = { probe self-check }
samples = 4
lines = 3
bands = 2
data type = 12
interleave = bsq
"""


def probe_hdr_parser():
    print("=" * 60)
    print("HDR PARSER (pure python, no ENVI needed)")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from envi_bridge import parse_hdr_text
        fields = parse_hdr_text(SAMPLE_HDR)
        print("  samples=%s lines=%s bands=%s data type=%s interleave=%s" % (
            fields.get("samples"), fields.get("lines"), fields.get("bands"),
            fields.get("data type"), fields.get("interleave")))
        ok = (fields.get("samples") == "4" and fields.get("bands") == "2")
        print("  parser self-check:", "ok" if ok else "MISMATCH")
        return ok
    except Exception as e:
        print("  parser failed:", e)
        return False


def try_task_names(IDL, envi):
    """多策略抽样 ENVITask 任务名，返回 (names, strategy)。"""
    strategies = []
    # 策略 A：ENVI 对象上的任务目录属性（版本间命名不一，逐个试）
    for attr in ("TASK_NAMES", "TaskNames", "TASKS", "Tasks"):
        try:
            val = getattr(envi, attr)
            if callable(val):
                val = val()
            names = [str(x) for x in list(val)]
            if names:
                return names, "envi.%s" % attr
        except Exception as e:
            strategies.append("%s: %s" % (attr, e))
    # 策略 B：IDL 表达式求值（ENVITask 目录函数在新版本里是 ENVITaskNames）
    for expr in ("ENVITaskNames()", "ENVITask(/LIST)"):
        try:
            val = IDL(expr)
            names = [str(x) for x in list(val)]
            if names:
                return names, "IDL(%s)" % expr
        except Exception as e:
            strategies.append("%s: %s" % (expr, e))
    print("  task-name strategies all failed:")
    for s in strategies:
        print("    -", s)
    return [], None


def main():
    probe_hdr_parser()
    print("=" * 60)
    print("IDLPY")
    try:
        from idlpy import IDL
        print("  idlpy import: ok")
    except Exception as e:
        print("  idlpy import failed:", e)
        print("  => 本机没有可用的 IDL/ENVI Python 桥；inventory 的 .hdr 解析不受影响。")
        return 1
    print("=" * 60)
    print("ENVI SESSION (HEADLESS)")
    envi = None
    try:
        envi = IDL.ENVI(HEADLESS=1)
        print("  ENVI session started: ok")
    except Exception as e:
        print("  ENVI session failed:", e)
        print("  => 常见原因：许可不可用或 ENVI 未正确安装。停下回报，不要反复重试。")
        return 1
    try:
        for label, fn in (
            ("ENVI version", lambda: getattr(envi, "VERSION", None)),
            ("IDL version (!version.release)", lambda: IDL("!version.release")),
            ("IDL build (!version.build_date)", lambda: IDL("!version.build_date")),
        ):
            try:
                val = fn()
                if callable(val):
                    val = val()
                print("  %s: %s" % (label, val))
            except Exception as e:
                print("  %s: <unavailable: %s>" % (label, e))
    finally:
        pass
    print("=" * 60)
    print("ENVITASK NAMES (sample)")
    names, via = try_task_names(IDL, envi)
    if names:
        print("  strategy:", via)
        print("  total:", len(names))
        for n in names[:50]:
            print("  -", n)
        if len(names) > 50:
            print("  ... (%d more)" % (len(names) - 50))
    else:
        print("  <no task names obtained; see strategy failures above>")
    try:
        envi.Close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
