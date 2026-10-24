# -*- coding: utf-8 -*-
"""
probe_api.py — globalmapper 模块 API 校准探针（只读）
用途：首次部署或版本变更时运行一次，输出本机 globalmapper 模块的可用性、
版本候选与各功能组候选函数的命中清单，以及模块公开名称全表，
供维护者据此收紧桥接脚本。输出为多行文本（非 JSON），请完整回传，不要删减。

注意：该模块仅随 Global Mapper Pro 提供；标准版没有 Python 模块，
探针在本机找不到模块属于版本/许可形态问题，不是脚本故障。
"""
import io
import sys

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

FUNCTION_GROUPS = {
    "version": ["GM_GetVersion", "GM_GetVersionInfo", "GM_GetGlobalMapperVersion",
                "GM_GetProductVersion", "GetVersion"],
    "load": ["GM_LoadWorkspace", "GM_LoadLayer", "GM_LoadLayerList",
             "GM_OpenWorkspace", "GM_LoadLayers"],
    "layer_list": ["GM_GetLayerList", "GM_GetLoadedLayerList", "GM_GetAllLayers",
                   "GM_ListLayers", "GM_GetLayers"],
    "layer_info": ["GM_GetLayerInfo", "GM_GetLayerDescription", "GM_GetLayerName"],
    "layer_visible_get": ["GM_GetLayerVisible", "GM_IsLayerVisible",
                          "GM_GetLayerEnabled", "GM_IsLayerEnabled"],
    "layer_visible_set": ["GM_SetLayerVisible", "GM_ShowLayer", "GM_HideLayer",
                          "GM_SetLayerEnabled", "GM_EnableLayer", "GM_DisableLayer",
                          "GM_SetLayerDrawStyle"],
    "zoom_view": ["GM_ZoomToLayer", "GM_SetViewToLayer", "GM_ViewLayer",
                  "GM_SetDisplayExtent", "GM_SetViewRect", "GM_SetViewBounds"],
    "layer_bounds": ["GM_GetLayerBoundingBox", "GM_GetLayerBounds",
                     "GM_GetLayerExtent"],
    "export": ["GM_ExportRaster", "GM_ExportRasterEx", "GM_ExportWebFormat",
               "GM_ExportPackage", "GM_ExportMapImage", "GM_ExportVector"],
    "close": ["GM_CloseLayer", "GM_UnloadLayer", "GM_CloseAllLayers",
              "GM_UnloadAllLayers"],
}


def main():
    try:
        import globalmapper
    except Exception as e:
        print("globalmapper import failed:", e)
        print("hint: 该模块仅随 Global Mapper Pro 提供；请确认 Pro 版已安装，"
              "且当前解释器能找到模块目录（可参考 GM 安装目录下的 Python 示例，"
              "或把模块目录加入 PYTHONPATH 后重试一次，仍失败则停下回报）")
        return 1
    print("globalmapper file:", getattr(globalmapper, "__file__", "unknown"))
    for attr in ("__version__", "VERSION", "version"):
        if hasattr(globalmapper, attr):
            val = getattr(globalmapper, attr)
            if not callable(val):
                print("globalmapper %s: %r" % (attr, val))
    print("=" * 60)
    print("FUNCTION CANDIDATE HITS（命中=本机模块里确实有这个名字）")
    for group, cands in FUNCTION_GROUPS.items():
        print("-" * 60)
        print("GROUP %s" % group)
        for name in cands:
            fn = getattr(globalmapper, name, None)
            print("  [%s] %s" % ("HIT " if callable(fn) else "miss", name))
    print("=" * 60)
    names = [n for n in dir(globalmapper) if not n.startswith("_")]
    print("globalmapper top-level public names (%d):" % len(names))
    print(", ".join(names))
    gm_like = [n for n in names if n.startswith("GM_")]
    print("GM_* names (%d):" % len(gm_like))
    print(", ".join(gm_like))
    return 0


if __name__ == "__main__":
    sys.exit(main())
