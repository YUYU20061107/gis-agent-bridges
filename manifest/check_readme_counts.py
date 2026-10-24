# -*- coding: utf-8 -*-
"""
check_readme_counts.py — 校验根 README 软件矩阵的「MCP 工具数」与
manifest/tools-manifest.json 一致。口径：矩阵单元格取第一个整数
（如 arcmap 的「10＋无头 6 动作」取 10，即其 MCP 工具数；无头桥动作数
不在本校验范围）。不一致 exit 1 并逐项打印差异。

用法：python3 manifest/check_readme_counts.py [--root <仓库根>]
"""
import argparse
import json
import os
import re
import sys


def parse_matrix(readme_path):
    counts = {}
    with open(readme_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            m = re.match(r"^`([a-z0-9-]+)/`$", cells[1])
            if not m:
                continue
            num = re.search(r"\d+", cells[3])
            if num:
                counts[m.group(1)] = int(num.group(0))
    return counts


def main():
    ap = argparse.ArgumentParser(prog="check_readme_counts")
    ap.add_argument("--root", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    readme_counts = parse_matrix(os.path.join(root, "README.md"))
    with open(os.path.join(root, "manifest", "tools-manifest.json"),
              encoding="utf-8") as f:
        manifest = json.load(f)
    diffs = []
    for entry in manifest["packages"]:
        pkg = entry["package"]
        if "error" in entry:
            diffs.append("%s: manifest 探测失败（%s），无法校验" % (pkg, entry["error"]))
            continue
        want = entry["tool_count"]
        got = readme_counts.get(pkg)
        if got is None:
            diffs.append("%s: 根 README 矩阵未找到该包行" % pkg)
        elif got != want:
            diffs.append("%s: 根 README 矩阵写 %d，manifest 实测 %d" % (pkg, got, want))
    for pkg in sorted(set(readme_counts) - {e["package"] for e in manifest["packages"]}):
        diffs.append("%s: 根 README 矩阵有行，但 manifest 无此包" % pkg)
    if diffs:
        print("README 工具数与 manifest 不一致：")
        for d in diffs:
            print("  - " + d)
        return 1
    print("OK: 根 README 矩阵工具数与 manifest 全部一致（%d 包）"
          % len(manifest["packages"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
