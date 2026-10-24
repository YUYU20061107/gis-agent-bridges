# CHANGELOG —— arcmap-bridge-lite v0.3-lab2（魔改版）

基线：arcmap-bridge-lite v0.2（三动作只读：preflight / backup / inspect）
改后：v0.3-lab2（三只读 + 三受控写），2026-10-25 在 ArcGIS Desktop 10.8 + Python 2.7.16 实机跑通。

## 一、新增的写动作（都要显式 `--confirm-write`，不覆盖原件）

### georef —— 一次多项式（仿射）配准
```
"C:\Python27\ArcGIS10.x\python.exe" scripts/arcmap_bridge.py georef ^
    --image <影像.jpg> --points <控制点.json> --out <输出目录> [--sr 4326] [--rectify] --confirm-write
```
- 控制点 JSON：`{"pairs":[{"id":1,"pixel":[col,row],"map":[lon,lat]}, ...]}`
- 纯 Python 3×3 高斯消元解 6 个未知数（不依赖 numpy / pyproj）
- 输出：`coef_x{a0,a1,a2}`、`coef_y{b0,b1,b2}`、逐点 `error_m`、`rms_m`、`max_m`、`pixel_size_m`
- 落盘：`.jgw` 世界文件、`<名>_geo.jpg`（原图+世界文件）、`<名>_geo.tif`（带 34264 旋转项）
- `--rectify` 追加 `<名>_rectify.tif`（正北对齐，BILINEAR），并回报每个文件字节数

### mkvector —— 由 JSON 生成 shapefile
```
... mkvector --spec <图层.json> --out <输出目录> --confirm-write
```
- spec：`{spatial_reference, layers:[{name, geometry(Polyline|Polygon), fields, features:[{coords, attrs}]}]}`
- 每层回写 `features_written` / `features_counted`（两者必须相等才可信）与文件字节数

### buildmxd —— 套模板组装 .mxd 并可选导出布局图
```
... buildmxd --template <.mxd> --layers a,b,c --out <.mxd> [--extent xmin,ymin,xmax,ymax] [--export-png x.png] [--dpi 100] --confirm-write
```
- 先 `saveACopy` 再改，回报每层 `is_broken`、`scale`、输出字节数

## 二、修掉的两个 py2 坑（这两个是 v0.2 直接跑不通的原因）

1. **`emit()` 中文崩溃**：`json.dumps(..., ensure_ascii=False)` 在 py2 下把 UTF-8 字节串
   当 ASCII 解码 → `UnicodeDecodeError: 'ascii' codec can't decode byte 0xef`。
   改法：`_to_text()` 递归转 unicode → `dumps(ensure_ascii=False).encode('utf-8')` →
   py3 写 `sys.stdout.buffer`、py2 写 bytes 到 `sys.stdout`，全失败退回 `ensure_ascii=True`。
2. **`sys.argv` 是 ANSI（GBK）字节串**：按 UTF-8 解码后中文路径变乱码，arcpy 报
   `ERROR 000732: Input Dataset or Feature Class ... does not exist or is not supported`。
   改法：`_dec()` 依次尝试 UTF-8 → `sys.getfilesystemencoding()`/mbcs/gbk → latin-1。

## 三、本机校准发现（已同步写进 SKILL.md）

| # | 现象 | 处置 |
|---|---|---|
| 3 | `Warp_management` 任何写法都报 `ERROR 000735: Source Control Points: Value is required` | 改用 `ProjectRaster_management(geo.jpg, out.tif, sr, "BILINEAR")` |
| 4 | `arcpy.Describe(raster).width/.meanCellWidth` 抛 `AttributeError: Method width does not exist`；`Describe(shp).spatialReference` 同样不存在 | 行列数用 `GetRasterProperties_management(COLUMNCOUNT/ROWCOUNT)`；要素数用 `GetCount_management`；坐标系读 `.prj`；范围读 `.shp` 头偏移 36 起的 4 个 `<d` |
| 5 | ArcMap 把 3 波段影像当单波段渲染成蓝色渐变（原始 jpg 拖进去也一样，目录树显示 Value High:255 Low:0） | 本机 ArcGIS 光栅显示组件问题，不是数据问题（PIL/GDAL 读都是正常 RGB）。成果图不要依赖 `ExportToPNG`，改自绘合成 |

## 四、lab2-scripts/（本次作业的整条流水线）

| 文件 | 作用 |
|---|---|
| `extract_features.py` | 从老师的标注参考图里按颜色掩膜提取 5 类要素：连通域 + Moore 边界跟踪 + Douglas-Peucker 化简；红色道路走 Zhang-Suen 细化 + 骨架追踪（共线优先）；白框用 ROI 内膨胀+反选取最大不触边区域 |
| `affine.json` / `control_points.json` | 7 个控制点（图钉针尖）的像素坐标与经纬度，以及解出的一次多项式系数 |
| `vector_spec.json` | 交给 `mkvector` 的图层定义（5 层，含 Len_m / Area_ha 属性） |
| `compose_figures.py` | 报告配图：控制点图、成果叠加图（图例/比例尺/指北针）、图层清单，全部 PIL 自绘 |
| `make_report.py` | python-docx 生成实验报告，附中文字数统计（本次 767 字 + 142 词） |
| `features/features.json` | 提取结果原始几何（像素坐标 + 经纬度） |

重跑顺序：`extract_features.py` → `arcmap_bridge.py georef` → `mkvector` → `buildmxd` → `compose_figures.py` → `make_report.py`。
脚本里写死了本机绝对路径（`<本机临时目录>\...`），换机器要改开头的 `TMP` / `FEAT` / `SPEC` 常量。

## 五、本次实测结果（可作回归基线）

- 控制点 7 个，一次多项式：RMS **2.3884 m**，max **3.6348 m**，像元 0.9165×0.9235 m
- `a0=113.57851652332934  a1=8.900644961248106e-06  a2=1.5686181796533173e-07`
- `b0=22.3523537019284  b1=1.0828374441830107e-07  b2=-8.294916650537204e-06`
- 矢量：Road 242 段 / 13922.5 m；Buildings 9 / 3.02 ha；GreenLand 1 / 9.30 ha；Lake 1 / 2.97 ha；Liyuan 4 / 3.90 ha
- 5 层 shapefile 全部 `.prj = GCS_WGS_1984`，`features_written == features_counted`

## 六、环境
ArcGIS Desktop 10.8（10.8.12790）、`C:\Python27\ArcGIS10.8\python.exe`（2.7.16, 32-bit）、
Windows；无 ArcGIS Pro。LibreOffice 用于 doc→pdf 预览。
