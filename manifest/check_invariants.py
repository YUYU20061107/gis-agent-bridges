# -*- coding: utf-8 -*-
"""
check_invariants.py — 安全不变量静态自检（对 17 包 live/mcp_server.py
与 live/inapp_bridge.py，如有）

检查口径（先声明，后检查；不为变绿放宽）：
  1. confirm 闸：工具清单（经 build_manifest 的实启探测取得）中凡
     「写/执行类」工具——判定标准：inputSchema 含 confirm 属性，或描述
     含「【写」/「【执行」标记——必须同时满足：
       (a) inputSchema 含 confirm 属性；
       (b) 执行侧存在 confirm 判断：有 inapp 桥的包查其 tool_<去前缀名>
           处理函数体；无 inapp 桥的包（envi/globalmapper/fme/mapgis）
           查 mcp_server.py 中处理该工具的函数体。函数体判定＝函数源码
           文本含 "confirm" 且含拒绝语义（"is not True" / "!= True" /
           "not args" 等宽松匹配：含 "confirm" 即记为有判断，再由人工
           口径复核——本脚本只做静态存在性检查，不做语义证明）。
     视图级工具（描述「【视图级」：只改显示、可逆）与导出类工具
     （*_export_*：写调用方指定路径的新文件）按现行设计不设 confirm，
     不在本项范围，但会逐项列出供复核。
  2. 绑定地址：被检文件全文不得出现 "0.0.0.0"；有 inapp 桥的包还必须
     出现 127.0.0.1 绑定证据（HOST 常量或 bind 调用）。
  3. 无任意代码执行工具：工具名不得命中 exec / eval / run_code /
     run_python / execute_code / shell / arbitrary 等模式。
  4. token 校验：有 inapp 桥的包，其 inapp 文件须含 token 比较与
     BAD_TOKEN 拒绝；无 inapp 桥的包，须在 mcp_server.py 里存在 token
     机制证据（BAD_TOKEN 或 *_BRIDGE_TOKEN 环境变量校验或 arguments
     token 字段比较）。

输出：逐包逐项结构化结论（JSON 同步打印一份摘要），全过 exit 0，
任一不过 exit 1 并指出包与工具。

用法：python3 manifest/check_invariants.py [--root <仓库根>]
"""
import argparse
import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_manifest  # noqa: E402

EXEC_PATTERNS = ["exec", "eval", "run_code", "run_python", "execute_code",
                 "shell", "arbitrary"]


def func_bodies(src):
    """函数名 -> 源码文本（含装饰器起止行内的函数体）"""
    out = {}
    try:
        tree = ast.parse(src)
    except Exception:
        return out
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            start = node.lineno - 1
            end = getattr(node, "end_lineno", None)
            if end is None:
                end = start + 1
                for sub in ast.walk(node):
                    if getattr(sub, "lineno", 0) > end:
                        end = sub.lineno
            out[node.name] = "\n".join(lines[start:end])
    return out


def find_handler_body(bodies, src, candidate_names):
    for name in candidate_names:
        if name in bodies:
            return bodies[name]
    # 兜底：找函数体中出现工具名字面量的函数
    for _name, body in bodies.items():
        for cand in candidate_names:
            if cand and ("'%s'" % cand in body or '"%s"' % cand in body):
                return body
    return None


def check_package(root, entry):
    pkg = entry["package"]
    live = os.path.join(root, pkg, "live")
    mcp_path = os.path.join(live, "mcp_server.py")
    inapp_path = os.path.join(live, "inapp_bridge.py")
    has_inapp = os.path.isfile(inapp_path)
    mcp_src = open(mcp_path, encoding="utf-8").read() if os.path.isfile(mcp_path) else ""
    inapp_src = open(inapp_path, encoding="utf-8").read() if has_inapp else ""
    result = {"package": pkg, "has_inapp_bridge": has_inapp,
              "violations": [], "notes": []}
    if "error" in entry:
        result["violations"].append("工具清单探测失败：%s" % entry["error"])
        return result

    bodies_inapp = func_bodies(inapp_src) if has_inapp else {}
    bodies_mcp = func_bodies(mcp_src)
    headless_handler_file = "mcp_server.py"

    for tool in entry["tools"]:
        name = tool["name"]
        desc = tool.get("description") or ""
        marked_write = ("【写" in desc) or ("【执行" in desc)
        is_write = tool["requires_confirm"] or marked_write
        if desc.startswith("【视图级"):
            result["notes"].append("%s: 视图级（可逆、无 confirm，按设计）" % name)
            continue
        if "_export_" in name and not is_write:
            result["notes"].append(
                "%s: 导出类（写调用方指定路径的新文件、无 confirm，按设计）" % name)
            continue
        if not is_write:
            continue
        # (a) schema 必须含 confirm
        if not tool["requires_confirm"]:
            result["violations"].append(
                "%s: 标注为写/执行类但 inputSchema 无 confirm 属性" % name)
            continue
        # (b) 执行侧 confirm 判断
        # 工具名前缀取工具名首段（如 arcgis-pro 包的工具前缀是 arcgis_）
        prefix = name.split("_", 1)[0] + "_"
        short = name[len(prefix):] if name.startswith(prefix) else name
        if has_inapp:
            body = find_handler_body(bodies_inapp, inapp_src,
                                     ["tool_" + short, short])
            where = "inapp_bridge.py"
        else:
            body = find_handler_body(bodies_mcp, mcp_src,
                                     ["tool_" + short, short, name])
            where = headless_handler_file
        if body is None:
            result["violations"].append(
                "%s: 在 %s 中找不到处理函数，无法证实 confirm 判断" % (name, where))
        elif "confirm" not in body:
            result["violations"].append(
                "%s: %s 的处理函数体内无 confirm 判断" % (name, where))

    # 2. 绑定地址
    for label, src in (("mcp_server.py", mcp_src), ("inapp_bridge.py", inapp_src)):
        if src and "0.0.0.0" in src:
            result["violations"].append("%s: 出现 0.0.0.0 绑定" % label)
    if has_inapp and "127.0.0.1" not in inapp_src:
        result["violations"].append("inapp_bridge.py: 未找到 127.0.0.1 绑定证据")

    # 3. 无任意代码执行工具
    for tool in entry["tools"]:
        low = tool["name"].lower()
        for pat in EXEC_PATTERNS:
            if pat in low:
                result["violations"].append(
                    "%s: 工具名命中任意执行模式 '%s'" % (tool["name"], pat))

    # 4. token 校验
    if has_inapp:
        if "BAD_TOKEN" not in inapp_src or "token" not in inapp_src.lower():
            result["violations"].append(
                "inapp_bridge.py: 未找到 token 校验（BAD_TOKEN）证据")
    else:
        has_bad = "BAD_TOKEN" in mcp_src
        has_env = re.search(r"[A-Z_]*BRIDGE_TOKEN", mcp_src) is not None
        has_arg_token = '"token"' in mcp_src or "'token'" in mcp_src
        if not (has_bad or (has_env and has_arg_token)):
            result["violations"].append(
                "mcp_server.py: 未找到 token 校验机制证据")
    return result


def main():
    ap = argparse.ArgumentParser(prog="check_invariants")
    ap.add_argument("--root", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    entries = [build_manifest.probe(root, p) for p in build_manifest.PACKAGES]
    results = [check_package(root, e) for e in entries]
    bad = 0
    for r in results:
        status = "PASS" if not r["violations"] else "FAIL"
        if r["violations"]:
            bad += 1
        print("%-13s %s (inapp=%s)" % (r["package"], status, r["has_inapp_bridge"]))
        for v in r["violations"]:
            print("    VIOLATION: " + v)
        for n in r["notes"]:
            print("    note: " + n)
    print(json.dumps({"all_pass": bad == 0,
                      "packages_failed": bad}, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
