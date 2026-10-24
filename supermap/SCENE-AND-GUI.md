# 三维场景与 GUI 保存（iDesktop 10i / iobjectspy 10.1）

本文件解决两件事：**无头环境怎么造三维场景**，以及 **在 iDesktop 里保存场景时怎么不丢**。
来源：2026-10-24 真实工程实战（轨迹点线球面场景，最终在 iDesktop 10i 打开、保存、验收）。

## 1. 无头能力边界（先说清楚，别承诺做不到的事）

- iobjectspy 10.1 **没有 realspace 的 Python 包装**：`Scene` / `SceneLayers` 等类需要
  原生库 `WrapjMObjects.dll`，在无头环境会 `UnsatisfiedLinkError: Can't find dependent
  libraries`。因此**不要承诺 headless 建三维图层或出三维图**，也不要反复试。
- 但 **Scenes 是 XML 驱动的**：可以读取、写入、注入场景 XML 并持久化，iDesktop 打开后
  正常渲染。无头能做的是“生成/校验场景 XML”，渲染与截图交给 iDesktop GUI。

## 2. 场景 XML：来源与结构

- 模板来源（任选）：
  - 安装目录示例：`<iDesktop>\SampleData\3D\CBDDataset\CBD.smwu` 里的场景，
    `ws._jobject.getScenes().getSceneXML("CBD")` 即可导出；
  - 本包 `templates/scene_globe_template.xml`（即上述 CBD 场景 XML 的副本，含球面设置、
    相机、KML/模型图层样例）。
- 关键节点（命名空间 `sml:`）：

```xml
<sml:Scene>
  <sml:Version>20090106</sml:Version>
  <sml:Name>场景名</sml:Name>
  <sml:SceneType>GLOBE</sml:SceneType>
  <sml:Bounds><sml:Left>…</sml:Left>…</sml:Bounds>
  <sml:Cameras>
    <sml:Camera>
      <sml:Name>name</sml:Name>
      <sml:camPosition><sml:x>…</sml:x><sml:y>…</sml:y><sml:z>…</sml:z></sml:camPosition>
      <sml:Orientation><sml:x>…</sml:x><sml:y>…</sml:y><sml:z>…</sml:z><sml:w>…</sml:w></sml:Orientation>
      <sml:ProjectionType3D>PT_PERSPECTIVE</sml:ProjectionType3D>
    </sml:Camera>
  </sml:Cameras>
  <sml:Layers>
    <sml:Layer>
      <sml:Caption>显示名</sml:Caption>
      <sml:DataSourceAlias>数据集名@数据源别名</sml:DataSourceAlias>
      <sml:LayerName>数据集名@数据源别名</sml:LayerName>
      <sml:DatasetType>Point|Line|Region|Model</sml:DatasetType>
      <sml:QueryDef>Rect2D(Left,Right,Top,Bottom)</sml:QueryDef>
      …
    </sml:Layer>
  </sml:Layers>
</sml:Scene>
```

- 注入：`scenes = ws._jobject.getScenes()`；`scenes.add(name, xml)`（返回下标）；
  校验 `scenes.getCount()` 与 `scenes.getSceneXML(name)`；最后 `ws.save()`。
- 已存在场景：`getSceneXML(name)` / `setSceneXML(name, xml)` / `remove(name)`。
- 场景里引用的数据源别名 = 工作空间里数据源的别名（udbx 文件名去扩展名），
  移动时整个目录一起复制就不会失效。

## 3. 相机（ECEF 与 SuperMap 的换轴）

- `camPosition` 是 ECEF 坐标换轴后的值：`pos_sm = (Y_ecef, Z_ecef, -X_ecef)`。
  可用北京 ECEF ≈ (-2.14e6, 4.39e6, 4.09e6) 对照样例 (4.38e6, 4.09e6, -2.18e6) 验证。
- `Orientation` 是四元数 (x, y, z, w)，由相机旋转矩阵求得；`alt` 是距地表高度（米）。
- 若算出来的方向不对（现象：地球转到别的大陆），**别硬调四元数**——在 iDesktop 里
  右键图层「缩放到本图层」，再保存场景，最省事且一定对。

## 4. iDesktop GUI 保存流程（关键：两步保存）

1. 启动：`<iDesktop>\Bin\SuperMap Desktop.exe "<工作空间路径>"`。
2. 工作空间管理器 → 展开「场景」→ 双击场景名 → 等地球/场景出现。
3. 图层管理器右键目标图层 → **缩放到本图层**；需要时打开属性表核对字段（如 DateStr）。
4. **Ctrl+S**：先弹「保存」场景对话框（勾选场景 → 保存），再弹「保存工作空间」
   （关窗时）→ 选「是」。**场景保存 ≠ 工作空间保存**，两次都要确认。
5. 验证：`workspace.smwu` 的 mtime 变化；只读重开 `scenes>0`、场景 XML 里图层数正确。
6. 截图：用 windows computer use 截图并另存，注意不要把无关窗口截进去。

## 5. 排错

| 现象 | 原因 | 处置 |
|---|---|---|
| 场景打开全黑/无图层 | DataSourceAlias 或 DatasetType 不匹配 | 用工作空间实际别名/类型重生成 XML |
| 场景里有图层但看不见 | 图层被隐藏或相机在别处 | 图层管理器勾选可见；缩放到本图层 |
| 场景在，重开消失了 | 只保存了场景、没保存工作空间 | 关窗时选「是」保存工作空间 |
| `UnsatisfiedLinkError: WrapjMObjects` | 无头缺 realspace 原生库 | 不要在建数据阶段用；走 XML 或 GUI |
| 打开场景很慢 | 首次加载球面影像/缓存 | 等几秒；换机器首次也会慢 |

## 6. 交付建议

- 工程文件里同时给：`*.smwu`（含场景）+ 场景截图 PNG + 一句话打开路径。
- 三维场景验收最低标准：换目录重开 → `scenes == 1` → 场景 XML 含全部图层 → iDesktop 实际可见。
