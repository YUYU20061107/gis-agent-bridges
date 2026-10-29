# -*- coding: utf-8 -*-
"""gis-agent-bridges 快速验证工具（纯标准库，不联网、不安装依赖）。

用途：
  * --list                 列出 17 个包、MCP 服务名与工具数；
  * --package qgis --selftest
                           运行指定包的离线协议自检；
  * --package qgis --print-config
                           把该包 examples/mcp-client-config.json 中的
                           <ABSOLUTE_PATH_TO_PACKAGE> 替换为本仓根目录的
                           绝对路径并输出，可直接合并进 MCP 客户端配置；
  * --sample-qgis          用 QGIS 无头解析器盘点仓内最小样本工程，
                           不需要安装 QGIS。

注意：自检通过只说明协议层可运行，不等于任何包已完成真实软件实机校准。
仓库级工具按 Python 3.11+ 验证；SuperMap/ArcMap 等厂商运行时有各自的
解释器要求，见根 README 的 Python 版本表。
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "manifest", "tools-manifest.json")
SAMPLE_QGS = os.path.join(
    ROOT, "examples", "sample-data", "qgis", "minimal-project.qgs")


def load_packages():
    with open(MANIFEST, encoding="utf-8") as f:
        data = json.load(f)
    return {p["package"]: p for p in data["packages"]}


def print_list(packages):
    for name in packages:
        p = packages[name]
        print("%-14s %-30s tools=%s" % (
            name, p.get("server_name") or "", p.get("tool_count")))


def run_selftest(package):
    path = os.path.join(ROOT, package, "live", "selftest.py")
    if not os.path.isfile(path):
        print("selftest not found: %s" % path, file=sys.stderr)
        return 2
    print("Running offline protocol selftest for %s ..." % package)
    return subprocess.run([sys.executable, path], cwd=os.path.join(
        ROOT, package)).returncode


def print_config(package):
    path = os.path.join(ROOT, package, "examples", "mcp-client-config.json")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = text.replace("<ABSOLUTE_PATH_TO_PACKAGE>", ROOT)
    try:
        parsed = json.loads(text)
    except Exception as exc:
        print("config template is not valid JSON after substitution: %s" % exc,
              file=sys.stderr)
        return 2
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    print("\n# Merge the mcpServers object into your client's MCP config.",
          file=sys.stderr)
    print("# See docs/CLIENTS.md for common client config locations.",
          file=sys.stderr)
    return 0


def run_sample_qgis():
    script = os.path.join(ROOT, "qgis", "scripts", "verify_project.py")
    if not os.path.isfile(SAMPLE_QGS):
        print("sample project not found: %s" % SAMPLE_QGS, file=sys.stderr)
        return 2
    return subprocess.run(
        [sys.executable, script, SAMPLE_QGS],
        cwd=os.path.join(ROOT, "qgis", "scripts")).returncode


def main():
    ap = argparse.ArgumentParser(description="gis-agent-bridges quickstart")
    ap.add_argument("--list", action="store_true", help="列出全部包")
    ap.add_argument("--package", help="包目录名，如 qgis / pgrouting / istsos")
    ap.add_argument("--selftest", action="store_true", help="运行所选包的离线自检")
    ap.add_argument("--print-config", action="store_true",
                    help="输出所选包的 MCP 客户端配置片段")
    ap.add_argument("--sample-qgis", action="store_true",
                    help="盘点仓内最小 QGIS 样本工程（无需安装 QGIS）")
    args = ap.parse_args()

    if sys.version_info < (3, 11):
        print("Warning: repository tooling is verified on Python 3.11+; "
              "this interpreter is %s." % sys.version.split()[0],
              file=sys.stderr)

    packages = load_packages()
    if args.list or (not args.package and not args.sample_qgis):
        print_list(packages)
        return 0
    if args.sample_qgis:
        return run_sample_qgis()
    if args.package not in packages:
        print("unknown package: %s" % args.package, file=sys.stderr)
        print("available: %s" % ", ".join(packages), file=sys.stderr)
        return 2
    if args.selftest:
        return run_selftest(args.package)
    if args.print_config:
        return print_config(args.package)
    print("choose --selftest or --print-config for --package", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
