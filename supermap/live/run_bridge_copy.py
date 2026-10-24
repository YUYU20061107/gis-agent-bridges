# -*- coding: utf-8 -*-
"""在“工作空间副本”上启动实时桥（文件回退模式，iDesktop 10i 可用）。

用法::

    python run_bridge_copy.py "<工作空间.smwu>" [--work-dir <目录>]

行为：
  1) 把 .smwu 以及同目录（含一级子目录）的数据源 .udb/.udbx/.udd 复制到工作目录的
     时间戳子目录——相对路径的数据源因此仍然连得上；
  2) 以 SM_LIVE_WORKSPACE_PATH 指向副本，启动 inapp_bridge.py（前台进程，Ctrl+C 停止）。

原工作空间全程只读；桥的一切写操作（加图层/专题图/保存）只落在副本上。
桥的 discover 会如实返回 mode=file-fallback：它不是 iDesktopX 里那个实时对象，
界面不会跟着刷新。
"""
import os
import runpy
import shutil
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "inapp_bridge.py")
DATA_EXTS = (".udb", ".udbx", ".udd")


def copy_workspace(src, work_root):
    """复制工作空间与同级数据源，返回 (副本 smwu 路径, 副本目录, 复制的数据源数)。"""
    stem = os.path.splitext(os.path.basename(src))[0]
    dest = os.path.join(work_root, "%s-%s" % (stem, time.strftime("%Y%m%d-%H%M%S")))
    os.makedirs(dest)
    shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
    src_dir = os.path.dirname(os.path.abspath(src))
    copied = [0]

    def walk(base, depth):
        if depth > 1:
            return
        try:
            names = os.listdir(base)
        except Exception:
            return
        for name in names:
            full = os.path.join(base, name)
            if os.path.isdir(full):
                walk(full, depth + 1)
                continue
            if not name.lower().endswith(DATA_EXTS):
                continue
            rel = os.path.relpath(full, src_dir)
            target = os.path.join(dest, rel)
            parent = os.path.dirname(target)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent)
            try:
                shutil.copy2(full, target)
                copied[0] += 1
            except Exception as e:
                print("复制数据源失败: %s -> %s" % (rel, e))

    walk(src_dir, 0)
    return os.path.join(dest, os.path.basename(src)), dest, copied[0]


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    src = argv[0]
    if not os.path.isfile(src):
        print("工作空间不存在: %s" % src)
        return 2

    # 端口只有一个：已有桥在跑就别再起第二个（先结束旧进程再换工作空间）
    try:
        probe = socket.create_connection(("127.0.0.1", 47615), timeout=0.5)
        probe.close()
        print("[run_bridge_copy] 127.0.0.1:47615 已有桥在运行。")
        print("[run_bridge_copy] 要换工作空间，请先结束已有的桥进程（结束对应的 python.exe 进程）。")
        return 3
    except Exception:
        pass

    work_root = None
    if "--work-dir" in argv:
        i = argv.index("--work-dir")
        if i + 1 < len(argv):
            work_root = argv[i + 1]
    if not work_root:
        token_file = os.environ.get("SM_BRIDGE_TOKEN_FILE")
        if token_file:
            work_root = os.path.join(os.path.dirname(token_file), "work")
        else:
            work_root = os.path.join(os.path.expanduser("~"), "SuperMapBridgeWork")
    if not os.path.isdir(work_root):
        os.makedirs(work_root)

    copy_path, dest, n = copy_workspace(src, work_root)
    os.environ["SM_LIVE_WORKSPACE_PATH"] = copy_path
    # 切到副本目录：iobjectspy 会往 CWD 写 iobjectspy.log，CWD 只读会直接打不开工作空间
    try:
        os.chdir(dest)
    except Exception:
        pass
    print("[run_bridge_copy] 原工作空间（只读）: %s" % src)
    print("[run_bridge_copy] 工作副本: %s" % copy_path)
    print("[run_bridge_copy] 一并复制的数据源: %d 个" % n)
    print("[run_bridge_copy] token 文件: %s"
          % (os.environ.get("SM_BRIDGE_TOKEN_FILE") or "~/.supermap-live-bridge.token"))
    sys.stdout.flush()
    runpy.run_path(BRIDGE, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
